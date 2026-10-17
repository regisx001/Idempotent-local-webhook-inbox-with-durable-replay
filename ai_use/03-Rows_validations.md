# Simulation & Work Log: Idempotency, Monotonicity, and Failure-Driven Refinement

This document simulates and records the development cycle for **Idempotency** and **Monotonic Versioning**: the initial naive hypothesis, test failures, root cause analysis, architecture modifications, and final automated verification.

---

## 1. Initial Hypothesis & Naive Implementation

### The Approach
The initial attempt approached deduplication as a pre-processing filter and monotonic versioning as a simple dictionary lookup:

```python
# Naive approach
def deduplicate_deliveries(deliveries: list[typing.Any]) -> list[typing.Any]:
    seen = set()
    unique_deliveries = []
    for delivery in deliveries:
        key = json.dumps(delivery, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique_deliveries.append(delivery)
    return unique_deliveries
```

### The Expected Behavior (Mental Model)
1. Eliminate duplicate entries before processing.
2. Iterate through `unique_deliveries` and update `findings[finding_id]` whenever `version >= current_version`.

---

## 2. Testing & Observed Failures

### Test 1: Fresh Primary Fixture Run
**Command:**
```bash
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
```

**Observed Result:**
- Output was missing Row 2 entirely.
- `counts["duplicate"]` reported `0` (Expected: `1`).
- Row 3 (`delivery_id: "d1"`, `status: "resolved"`) had a different JSON string than Row 1 (`status: "open"`), so `json.dumps()` treated it as a completely new delivery instead of a **delivery conflict**.
- Exit code / count mismatch: `counts["rejected"]` was `3` instead of `4`.

### Test 2: Replay Against Persisted State
**Command:**
```bash
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
```

**Observed Result:**
- `counts["duplicate"]` reported `1` instead of `6`.
- `counts["applied"]` reported `3` instead of `0`.
- **Root Failure:** The local `seen = set()` only lived during process execution and ignored `scratch-state.json`. When a new process started, it re-applied all deliveries as if fresh, violating durable idempotency.

### Test 3: The Row 9 Edge Case (Version Conflict vs Key Reservation)
**Row 9 data:**
```json
{"delivery_id": "d7", "tenant": "north", "finding_id": "f1", "version": 3, "status": "open"}
```
- In Run 1, finding `f1` is already at `v3 resolved` (from Row 5 `d3`).
- Row 9 has version 3 with conflicting status (`open` vs `resolved`), so it was classified as `rejected` (version conflict).
- **The Bug:** If marked `rejected` and discarded without saving `d7` to `state["deliveries"]`:
  - When Run 2 is executed, Row 9 arrives again. Because `d7` was not saved, Run 2 tries to evaluate it against the finding again, producing another `rejected` count.
  - As a result, Run 2 produced `duplicate: 5, rejected: 4` instead of the required `duplicate: 6, rejected: 3`.

---

## 3. Root Cause Analysis

| Failure | Root Cause | Architectural Principle Violated |
|---|---|---|
| **Missing Row 2** | Pre-filtering pruned rows before result recording. | Every input row must have a 1-based index entry in `results`. Deduplication is an outcome classification, not a filter. |
| **Row 3 Missed Conflict** | Hashed entire row JSON instead of keying on `delivery_id`. | Idempotency key is `delivery_id`. Comparing raw payloads ignores the definition of a Delivery Conflict (same ID, different payload). |
| **Replay Failure** | `seen` set in process memory instead of durable file state. | State must survive across separate CLI process runs via `--state`. |
| **Row 9 Missing in Replay** | Treated all `rejected` rows as "not stored". | Only *malformed/foreign* rows are not stored. Valid deliveries with version conflicts must reserve their idempotency key in `state["deliveries"]`. |

---

## 4. Code Modifications

### Modification 1: Sequential In-Memory Event Processing
Replaced pre-filtering with sequential evaluation that evaluates both idempotency and monotonicity in order:

```python
for row_idx, row in enumerate(deliveries, start=1):
    is_valid, canonical, delivery_id, reason = validate_delivery_row(row, arguments.tenant)
    if not is_valid:
        results.append({
            "row": row_idx,
            "delivery_id": delivery_id,
            "outcome": "rejected",
            "reason": reason
        })
        counts["rejected"] += 1
        continue  # Malformed or foreign: DO NOT STORE KEY

    # Idempotency / Delivery identity check against state
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
            "reason": reason
        })
        continue  # Stop here! Findings are NOT modified for duplicate or conflict

    # New delivery ID: IMMEDIATELY reserve key in state
    state["deliveries"][delivery_id] = canonical

    # Monotonic version evaluation
    finding_id = canonical["finding_id"]
    version = canonical["version"]
    status = canonical["status"]

    current_finding = state["findings"].get(finding_id)
    if current_finding is None or version > current_finding["version"]:
        state["findings"][finding_id] = {"version": version, "status": status}
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
        "reason": reason
    })
```

### Modification 2: Crash-Safe Atomic Persistence
State is saved only upon successful completion of the batch, using a same-directory tempfile and atomic replacement:

```python
def save_state(state: dict[str, typing.Any], state_path: pathlib.Path) -> None:
    target = state_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp")
    try:
        content = json.dumps(state, indent=2, sort_keys=True) + "\n"
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(target)
    except Exception as error:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise ValueError(f"failed to save state: {error}") from error
```

---

## 5. Re-Testing & Verification

### Run 1: Fresh Primary Fixture
```bash
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
```
**Outcome Counts:**
```json
{
  "applied": 3,
  "duplicate": 1,
  "redundant": 0,
  "rejected": 4,
  "stale": 1
}
```
*Result: PASS (Matches README baseline).*

### Run 2: Replay Against Persisted State
```bash
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
```
**Outcome Counts:**
```json
{
  "applied": 0,
  "duplicate": 6,
  "redundant": 0,
  "rejected": 3,
  "stale": 0
}
```
*Result: PASS (Rows 1, 2, 4, 5, 8, 9 recognized as duplicates; rows 3, 6, 7 rejected).*

### Run 3: Secondary Fixture Replay
```bash
python3 app.py --input inputs/secondary.json --tenant north --state scratch-state.json
```
**Outcome Counts:**
```json
{
  "applied": 2,
  "duplicate": 0,
  "redundant": 1,
  "rejected": 0,
  "stale": 0
}
```
*Result: PASS (`s1` advances `f1` to v4; `s2` is redundant at v1; `s3` advances `f2` to v2).*

---

## 6. Automated Regression Tests

We added regression assertions in `tests/app_test.py`:
- `testCli_whenPrimaryRun_producesDocumentedCounts`: Checks fresh state counts.
- `testCli_whenPrimaryReplayed_producesDocumentedReplayCounts`: Verifies that run 2 yields 6 duplicates and 3 rejections.
- `testCli_whenSecondaryRunOnPrimaryState_producesDocumentedCounts`: Verifies cross-fixture durability and redundant status handling.
- `testCli_whenStateMalformed_exitsTwoAndPreservesBytes`: Ensures corrupted state triggers exit code 2 and leaves original bytes untouched.

**Test Run Output:**
```bash
$ python3 -m unittest discover -s tests -p '*_test.py' -v
testCli_whenHelpRequested_returnsUsage ... ok
testCli_whenInputMissing_reportsReadableError ... ok
testCli_whenJsonMalformed_reportsReadableError ... ok
testCli_whenPrimaryReplayed_producesDocumentedReplayCounts ... ok
testCli_whenPrimaryRun_producesDocumentedCounts ... ok
testCli_whenSecondaryRunOnPrimaryState_producesDocumentedCounts ... ok
testCli_whenStateMalformed_exitsTwoAndPreservesBytes ... ok
testValidateRow_whenForeignTenant_rejectsWithReason ... ok
testValidateRow_whenMissingOrEmptyField_rejects ... ok
testValidateRow_whenValidWithWhitespace_returnsTrimmedCanonical ... ok
testValidateRow_whenVersionBoolean_rejects ... ok
testValidateRow_whenVersionZero_rejects ... ok
testValidateTopLevel_whenTenantMismatch_raisesValueError ... ok

Ran 13 tests in 0.426s - OK
```
