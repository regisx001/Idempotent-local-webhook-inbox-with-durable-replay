"""Exercise scaffold: CLI I/O works; the assessed feature is intentionally absent."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import typing


VALID_STATUSES = {"open", "resolved"}


def validate_top_level_payload(payload: typing.Any, expected_tenant: str) -> list[typing.Any]:
    """Validate top-level payload structure and tenant match.

    Raises ValueError on fatal schema or tenant mismatch (exiting with code 2).
    """
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")

    tenant = payload.get("tenant")
    if not isinstance(tenant, str) or tenant.strip() != expected_tenant:
        raise ValueError(
            f"input tenant mismatch: expected {expected_tenant!r}, got {tenant!r}")

    deliveries = payload.get("deliveries")
    if not isinstance(deliveries, list):
        raise ValueError("input must contain a 'deliveries' array")

    return deliveries


def validate_delivery_row(
    row: typing.Any, expected_tenant: str
) -> tuple[bool, dict[str, typing.Any] | None, str, str | None]:
    """Validate a single delivery row against the contract.

    Returns:
        is_valid: bool
        canonical_payload: dict if valid, None if invalid
        delivery_id: trimmed delivery_id string (or empty if unparseable)
        reason: rejection reason string if invalid, None if valid
    """
    if not isinstance(row, dict):
        return False, None, "", "row must be an object"

    raw_delivery_id = row.get("delivery_id")
    raw_tenant = row.get("tenant")
    raw_finding_id = row.get("finding_id")
    version = row.get("version")
    raw_status = row.get("status")

    # Safe extraction of delivery_id for diagnostics
    delivery_id = str(raw_delivery_id).strip(
    ) if isinstance(raw_delivery_id, str) else ""

    # 1. Non-empty string checks
    if not isinstance(raw_delivery_id, str) or not raw_delivery_id.strip():
        return False, None, delivery_id, "delivery_id must be a non-empty string"

    if not isinstance(raw_tenant, str) or not raw_tenant.strip():
        return False, None, delivery_id, "tenant must be a non-empty string"

    if not isinstance(raw_finding_id, str) or not raw_finding_id.strip():
        return False, None, delivery_id, "finding_id must be a non-empty string"

    # 2. Tenant isolation check (membership is case-sensitive)
    tenant = raw_tenant.strip()
    if tenant != expected_tenant:
        return False, None, delivery_id, f"foreign tenant: {tenant}"

    # 3. Positive integer version check (excluding bool)
    if type(version) is not int or isinstance(version, bool) or version <= 0:
        return False, None, delivery_id, "version must be a positive integer"

    # 4. Status check
    if not isinstance(raw_status, str):
        return False, None, delivery_id, "status must be a string"
    status = raw_status.strip()
    if status not in VALID_STATUSES:
        return False, None, delivery_id, f"status must be 'open' or 'resolved', got '{status}'"

    canonical = {
        "tenant": tenant,
        "finding_id": raw_finding_id.strip(),
        "version": version,
        "status": status,
    }
    return True, canonical, delivery_id, None


def load_state(state_path: pathlib.Path, expected_tenant: str) -> dict[str, typing.Any]:
    """Load and validate local JSON state file.

    If absent, returns empty state. If malformed or wrong tenant, raises ValueError (exit 2).
    """
    if not state_path.exists():
        return {
            "tenant": expected_tenant,
            "deliveries": {},
            "findings": {},
        }

    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as error:
        raise ValueError(f"malformed state file JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("state file must be a JSON object")

    tenant = data.get("tenant")
    if not isinstance(tenant, str) or tenant.strip() != expected_tenant:
        raise ValueError(
            f"state tenant mismatch: expected {expected_tenant!r}, got {tenant!r}")

    deliveries = data.get("deliveries")
    if not isinstance(deliveries, dict):
        raise ValueError("state deliveries must be an object")

    findings = data.get("findings")
    if not isinstance(findings, dict):
        raise ValueError("state findings must be an object")

    for delivery_id, payload in deliveries.items():
        if not isinstance(delivery_id, str) or not delivery_id.strip():
            raise ValueError("state delivery_id must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("state delivery payload must be an object")
        if payload.get("tenant") != expected_tenant:
            raise ValueError("state delivery payload tenant mismatch")
        if not isinstance(payload.get("finding_id"), str) or not payload["finding_id"].strip():
            raise ValueError("state delivery payload missing finding_id")
        ver = payload.get("version")
        if type(ver) is not int or isinstance(ver, bool) or ver <= 0:
            raise ValueError("state delivery payload invalid version")
        if payload.get("status") not in VALID_STATUSES:
            raise ValueError("state delivery payload invalid status")

    for finding_id, finding in findings.items():
        if not isinstance(finding_id, str) or not finding_id.strip():
            raise ValueError("state finding_id must be a non-empty string")
        if not isinstance(finding, dict):
            raise ValueError("state finding must be an object")
        ver = finding.get("version")
        if type(ver) is not int or isinstance(ver, bool) or ver <= 0:
            raise ValueError("state finding invalid version")
        if finding.get("status") not in VALID_STATUSES:
            raise ValueError("state finding invalid status")

    return data


def save_state(state: dict[str, typing.Any], state_path: pathlib.Path) -> None:
    """Atomically save state JSON file via a temporary file in the same directory."""
    target = state_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp")
    try:
        content = json.dumps(state, indent=2, sort_keys=True) + "\n"
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(target)
    except Exception as error:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise ValueError(f"failed to save state: {error}") from error


def ingest_events(payload: dict[str, typing.Any], arguments: argparse.Namespace) -> dict[str, typing.Any]:
    """Process incoming deliveries according to idempotency and monotonic rules."""
    deliveries = validate_top_level_payload(payload, arguments.tenant)

    input_path = pathlib.Path(arguments.input).resolve()
    state_path = pathlib.Path(arguments.state).resolve()
    if input_path == state_path:
        raise ValueError("--state must not point to the input file")

    state = load_state(state_path, arguments.tenant)

    results: list[dict[str, typing.Any]] = []
    counts = {
        "applied": 0,
        "duplicate": 0,
        "redundant": 0,
        "rejected": 0,
        "stale": 0,
    }

    for row_idx, row in enumerate(deliveries, start=1):
        is_valid, canonical, delivery_id, reason = validate_delivery_row(
            row, arguments.tenant)
        if not is_valid:
            results.append({
                "row": row_idx,
                "delivery_id": delivery_id,
                "outcome": "rejected",
                "reason": reason,
            })
            counts["rejected"] += 1
            continue

        assert canonical is not None

        # Step 2: Idempotency / Delivery identity check
        if delivery_id in state["deliveries"]:
            stored = state["deliveries"][delivery_id]
            if stored == canonical:
                outcome = "duplicate"
                reason = "duplicate delivery"
                counts["duplicate"] += 1
            else:
                outcome = "rejected"
                reason = "delivery conflict"
                counts["rejected"] += 1

            results.append({
                "row": row_idx,
                "delivery_id": delivery_id,
                "outcome": outcome,
                "reason": reason,
            })
            continue

        # Step 3: New delivery_id -> Store canonical payload in state immediately
        state["deliveries"][delivery_id] = canonical

        # Step 4: Monotonic version check against finding
        finding_id = canonical["finding_id"]
        version = canonical["version"]
        status = canonical["status"]

        current_finding = state["findings"].get(finding_id)
        if current_finding is None or version > current_finding["version"]:
            state["findings"][finding_id] = {
                "version": version,
                "status": status,
            }
            outcome = "applied"
            reason = "finding updated"
            counts["applied"] += 1
        elif version < current_finding["version"]:
            outcome = "stale"
            reason = "stale version"
            counts["stale"] += 1
        else:  # version == current_finding["version"]
            if status == current_finding["status"]:
                outcome = "redundant"
                reason = "redundant status"
                counts["redundant"] += 1
            else:
                outcome = "rejected"
                reason = "version conflict"
                counts["rejected"] += 1

        results.append({
            "row": row_idx,
            "delivery_id": delivery_id,
            "outcome": outcome,
            "reason": reason,
        })

    # Save state atomically
    save_state(state, state_path)

    return {
        "results": results,
        "counts": counts,
        "findings": state["findings"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay synthetic webhook deliveries into a local JSON state file.")
    parser.add_argument(
        "--input", default="inputs/primary.json", help="UTF-8 fixture JSON")
    parser.add_argument("--tenant", default="north")
    parser.add_argument("--state", default="state.json",
                        help="Local state; absent file means empty state")
    arguments = parser.parse_args()
    try:
        payload = json.loads(pathlib.Path(
            arguments.input).read_text(encoding="utf-8"))
        result = ingest_events(payload, arguments)

        print(json.dumps(result, indent=2, sort_keys=True))

    except NotImplementedError as error:
        print(str(error), file=sys.stderr)
        return 3
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
