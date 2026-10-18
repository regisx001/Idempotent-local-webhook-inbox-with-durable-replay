# Architectural Decision Record (ADR) & Tradeoff Log

This document records the core architectural decisions, design rationale, trade-offs, and boundary constraints established for the **Idempotent Local Webhook Inbox**.

---

## 1. Decision Summary Matrix

| ID | Decision Area | Chosen Architecture | Key Alternative Considered | Primary Tradeoff |
|---|---|---|---|---|
| **ADR-01** | Ingestion Engine | Sequential in-order processing with live in-memory state mutation | Multi-stage pre-filtering pipeline (e.g. `deduplicate_deliveries`) | Simplicity & order-dependent consistency vs. streaming unbounded inputs |
| **ADR-02** | Decision Pipeline | Two-tier evaluation: Delivery Identity Gate $\rightarrow$ Entity Monotonicity Gate | Unified single-gate evaluation | Explicit distinction between delivery-level retries and entity-level version conflicts |
| **ADR-03** | Key Reservation | Immediate reservation of new valid `delivery_id` keys before version evaluation | Lazy reservation only on `applied` outcomes | Version-conflicted rows (Row 9) correctly deduplicate on replay |
| **ADR-04** | Durability & Atomicity | Same-directory temporary file write with POSIX atomic `os.replace` | Direct file write with in-place truncation | File system atomicity and crash resilience vs. temporary file overhead |
| **ADR-05** | Error & State Integrity | Strict fail-fast on malformed/foreign state with zero byte mutations | Automatic state repair or fallback to empty state | Data safety and error visibility vs. auto-recovery |
| **ADR-06** | Type System Validation | Strict type identity (`type(v) is int and not isinstance(v, bool)`) | Python standard `isinstance(v, int)` | Prevents boolean coercion (`version: true`) from corrupting state |

---

## 2. Deep Dive into Architectural Decisions & Tradeoffs

### ADR-01: Sequential In-Order Processing vs. Batch Pre-Filtering

- **Context:**
  Deliveries arrive in a batch array within `inputs/primary.json`. Events may have inter-dependencies where row $N$ modifies state that row $N+1$ depends on (e.g., Row 1 sets `d1` to open, Row 2 is an identical delivery of `d1`, and Row 3 conflicts with `d1`).
- **Initial Attempt:**
  Pre-filtering the list via a helper function (`deduplicate_deliveries`) using `seen = set()` and `json.dumps(row)`.
- **Why It Failed:**
  1. Dropping rows violated the acceptance criterion requiring 1-based indexed results for **every** input row.
  2. Hashing entire JSON payloads failed to detect Delivery Conflicts (same `delivery_id` with different payloads).
  3. Pre-filtering could not account for pre-existing state saved across separate CLI process runs.
- **Adopted Architecture:**
  A single sequential loop iterating through `enumerate(deliveries, start=1)`. The in-memory state dictionary (`state["deliveries"]` and `state["findings"]`) updates immediately after each row.
- **Tradeoff Analysis:**
  - *Advantage:* Absolute determinism. Perfectly models chronological event arrival and supports mid-run state evolution.
  - *Limitation:* State must fit comfortably in memory. Acceptable because the assessment specifies synthetic batch JSON files rather than unbounded streams.

---

### ADR-02: Two-Tier Decoupling: Delivery Identity vs. Entity Freshness

- **Context:**
  A webhook sender retries deliveries due to network timeouts, causing duplicates and out-of-order events.
- **Design Decision:**
  Decouple the pipeline into two orthogonal concerns:
  1. **Delivery Identity Check (Idempotency):**
     *"Have we seen this `delivery_id`?"*
     - If yes, compare canonical payloads:
       - Identical payload $\rightarrow$ `duplicate`.
       - Differing payload $\rightarrow$ `rejected` (`delivery conflict`).
     - **Short-circuit:** When an ID is already known, stop row processing immediately. Findings are never evaluated or touched.
  2. **Entity Version Check (Monotonic Progression):**
     *"Is this version newer than what is recorded for this `finding_id`?"*
     - Only evaluated for **new** delivery IDs.
     - `version > current` $\rightarrow$ `applied` (finding updated).
     - `version < current` $\rightarrow$ `stale`.
     - `version == current` and `status == current` $\rightarrow$ `redundant`.
     - `version == current` and `status != current` $\rightarrow$ `rejected` (`version conflict`).
- **Tradeoff Analysis:**
  - *Advantage:* Eliminates race conditions and prevents stale deliveries (like Row 4 `d2, v1`) from corrupting findings previously advanced by newer deliveries (Row 1 `d1, v2`).
  - *Consequence:* An event can be rejected for two completely different reasons: either a delivery key collision (`delivery conflict`) or an entity state conflict (`version conflict`).

---

### ADR-03: Key Reservation Timing (The Row 9 Edge Case)

- **Context:**
  In `inputs/primary.json`, Row 9 (`d7, f1, v3 open`) arrives when `f1` is already at `v3 resolved` (advanced by Row 5 `d3`). Row 9 has the same version (3) but conflicting status (`open` vs `resolved`), resulting in `rejected` (version conflict).
- **Design Dilemma:**
  Should rejected rows have their `delivery_id` recorded in `state["deliveries"]`?
- **Decision:**
  - **Schema-invalid and foreign rows (Rows 6 & 7):** Must **NOT** reserve their keys. If a corrected delivery arrives later with the same ID, it must be allowed.
  - **Version conflicts (Row 9):** **MUST** reserve their key. The delivery itself was validly received; it simply conflicted with existing entity state.
- **Evidence & Impact:**
  - If Row 9's key is not saved: when `primary.json` is replayed in Run 2, Row 9 is evaluated as a new row again, resulting in `duplicate: 5, rejected: 4`.
  - When Row 9's key is immediately reserved in Step 3: Run 2 recognizes `d7` as already stored with an identical canonical payload, producing `duplicate: 6, rejected: 3`. This matches the README specification.

---

### ADR-04: Crash-Safe Durability via Same-Directory Atomic Swapping

- **Context:**
  State must survive across separate CLI process runs. If the process is killed or encounters an OS write error midway through saving, existing state must not be corrupted or truncated.
- **Adopted Architecture:**
  ```python
  target = state_path.resolve()
  temp_path = target.with_name(f".{target.name}.tmp")
  temp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  temp_path.replace(target)
  ```
- **Tradeoff Analysis:**
  - *Why not write directly to `state_path`?* A crash mid-write leaves zero-length or truncated JSON.
  - *Why same directory (`target.with_name(...)`)?* On POSIX systems, `rename()` / `os.replace()` is only atomic when the source and destination reside on the **same filesystem mount**. Using `/tmp` or system temp directories risks a cross-device copy-and-unlink operation, which is non-atomic.

---

### ADR-05: Zero-Mutation Corrupted State Policy

- **Context:**
  How should the CLI behave when `--state` points to a corrupted JSON file or a file for a different tenant?
- **Adopted Architecture:**
  Validate state structure upon loading. If invalid, malformed, or tenant mismatches, fail fast with exit code **2** and do **not** write or touch the state file.
- **Tradeoff Analysis:**
  - *Alternative Considered:* Attempting to repair corrupt state or falling back to empty state.
  - *Decision:* Rejected. Auto-recovery could destroy salvageable user data. Preserving byte-level immutability ensures forensic safety. Automated tests verify `state_file.read_bytes() == corrupt_bytes`.

---

### ADR-06: Type Coercion Guard for Integer Versions

- **Context:**
  In Python, `bool` inherits from `int` (`issubclass(bool, int) is True`). Therefore, `isinstance(True, int)` evaluates to `True`.
- **Vulnerability:**
  If an incoming payload contains `"version": true`, naive validation treats it as integer `1`.
- **Adopted Architecture:**
  Strict identity check:
  ```python
  type(version) is int and not isinstance(version, bool) and version > 0
  ```
- **Tradeoff:**
  Requires explicit defensive code, but completely eliminates silent type coercion bugs.

---

## 3. Scope Boundaries & What Was Deferred

In accordance with the 24-hour assessment scope:

1. **Deferred: Distributed Locking / Concurrency:**
   - *Rationale:* The specification states: *"survives another CLI process... no concurrency or crash-injection framework is required."* File locks (`fcntl.flock`) or distributed mutexes were deferred to avoid platform-specific lock-contention issues.
2. **Deferred: Database / SQLite Storage:**
   - *Rationale:* JSON files are the required contract format. Adding SQLite would introduce unnecessary schema abstraction layers.
3. **Deferred: Network / HTTP Webhook Receiver:**
   - *Rationale:* The problem is strictly a local synthetic CLI. All synthetic events and state are local files.
