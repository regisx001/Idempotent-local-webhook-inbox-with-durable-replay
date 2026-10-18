# Idempotent Local Webhook Inbox

A zero-dependency, crash-resilient Python CLI that ingests webhook events into a local JSON state store. The inbox enforces transport-level idempotency, entity-level monotonic version progression, and atomic file persistence across separate process runs.

---

## 1. Quickstart & Prerequisites

- **Python Version:** Python 3.10 or later (standard library only; no third-party packages required).
- **Working Directory:** Commands should be executed from the repository root.

```bash
# Verify Python version and CLI usage
python3 --version
python3 app.py --help
```

---

## 2. Fixture Verification Commands

Execute the canonical three-run fixture workflow using a fresh, local state file (`scratch-state.json`):

```bash
# Clean any previous state file
rm -f scratch-state.json

# Run 1: Fresh primary ingestion
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json

# Run 2: Replay primary ingestion against saved state
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json

# Run 3: Secondary fixture ingestion on saved state
python3 app.py --input inputs/secondary.json --tenant north --state scratch-state.json
```

### Expected Observable Outcomes

| Ingestion Run | Command & Fixture | Applied | Duplicate | Stale | Redundant | Rejected | Final Finding State |
|---|---|:---:|:---:|:---:|:---:|:---:|---|
| **Run 1** | Primary (Fresh) | **3** | **1** | **1** | **0** | **4** | `f1` @ v3 (`resolved`), `f2` @ v1 (`open`) |
| **Run 2** | Primary (Replay) | **0** | **6** | **0** | **0** | **3** | `f1` @ v3 (`resolved`), `f2` @ v1 (`open`) |
| **Run 3** | Secondary (Evolution) | **2** | **0** | **0** | **1** | **0** | `f1` @ v4 (`open`), `f2` @ v2 (`resolved`) |

---

## 3. Automated Test Suite

The test suite contains 23 unit, schema validation, and edge-case regression tests. Tests can be executed from the repository root or any arbitrary directory:

```bash
python3 -m unittest discover -s tests -p '*_test.py' -v
```

### Coverage Summary
- **Baseline CLI:** Usage, missing files, malformed JSON inputs.
- **Fixture Benchmarks:** Exact primary run, replay deduplication, and secondary evolution counts.
- **Strict Validation:** String trimming, positive integer versions (`type(v) is int and not bool`), lowercase status matching (`open`/`resolved`), foreign tenant isolation.
- **Schema & State Integrity:** Detection of corrupt JSON, non-dict findings, list-valued status types in findings/deliveries (exits 2 with no traceback and 100% byte preservation).
- **Atomic Persistence & Write Failures:** Unit and integration verification that write failures during state replacement exit 2, log clean errors without tracebacks, leave no orphaned `.tmp` files, and preserve original state bytes.
- **Boundary Deduplication:** Proves that version-conflicted deliveries (e.g. Row 9, `d7`) reserve their idempotency keys and classify as `duplicate` upon replay.

---

## 4. Architecture & Core Guarantees

### Two-Tier Decision Pipeline
1. **Tier 1 (Transport Identity Gate):** Evaluates `delivery_id`. If previously stored with the identical canonical payload, classifies as `duplicate`. If the payload differs, classifies as `rejected` (`delivery conflict`). Neither outcome modifies findings.
2. **Immediate Key Reservation:** A valid `delivery_id` is recorded in state immediately upon initial evaluation, ensuring that stale and version-conflicted deliveries correctly deduplicate on replay. Invalid rows and foreign-tenant rows are never reserved.
3. **Tier 2 (Domain Monotonicity Gate):** Evaluates version ordering against the target finding.
   - $v > current$: `applied` (finding updated to new version and status).
   - $v < current$: `stale` (finding untouched).
   - $v == current$ with same status: `redundant` (finding untouched).
   - $v == current$ with different status: `rejected` (`version conflict`; finding untouched).

### Crash-Resilient Durability (ADR-04)
State is written to a sibling temporary file (`.{filename}.tmp`) and atomically swapped into place via POSIX `os.replace`. If a write fails at any point, the temporary file is unlinked, the existing state file is preserved without byte corruption, and the CLI exits with code 2.

### Exit Codes & Diagnostics
- **`0`**: Successful processing. Emits JSON on `stdout` with `results`, `counts`, and current `findings`.
- **`2`**: Fatal operational error (missing input file, malformed JSON, state schema corruption, tenant mismatch, write failure, or `--state` matching `--input`). Emits readable diagnostic `error: <message>` to `stderr` with no Python traceback.

---

## 5. Repository Structure

```
├── app.py                      # Main CLI and ingestion pipeline implementation
├── tests/
│   └── app_test.py             # 23 automated unit and regression tests
├── inputs/
│   ├── primary.json            # Primary business fixture with redeliveries
│   ├── secondary.json          # Secondary evolution fixture
│   └── malformed-input.txt     # Malformed input fixture for error handling
├── README.md                   # Concise operational and run guide (this document)
├── DECISION_LOG.md             # Architectural decision records (ADR-01 through ADR-06)
└── SUBMISSION.md               # Complete submission dossier (walkthrough, trace, AI note)
```
