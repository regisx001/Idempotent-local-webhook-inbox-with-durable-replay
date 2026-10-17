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
        print("SOMETHING")
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


def ingest_events(payload: dict[str, typing.Any], arguments: argparse.Namespace) -> dict[str, typing.Any]:
    """Implement the candidate README contract here; refactor freely."""
    deliveries = validate_top_level_payload(payload, arguments.tenant)

    # Validate each row (Step 1 of decision flow)
    # Further steps (state persistence, deduplication, monotonic versioning) will follow
    raise NotImplementedError(
        "STARTER: implement ingest_events; no feature output was produced")


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
