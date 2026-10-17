# Prompt :

Explain the problem to me clearly before I start solving it. Break down the requirements, explain what is expected from me, provide practical examples and edge cases, and suggest how I should approach the problem step by step.

Do not give me the solution, write code, or implement anything. I want to understand the problem, the reasoning behind it, and how to solve it independently.

# Response :


# Webhook Inbox: Problem Briefing

I read the README, starter `app.py`, fixtures, and smoke tests. This is the 04 "Idempotent local webhook inbox" exercise.

## 1. The problem in one paragraph

A partner system sends finding status events (`open` / `resolved`) and redelivers them after timeouts, sometimes out of order. You build a CLI that reads a batch of deliveries, decides what each one means, updates a local JSON state file, and prints a JSON report. Running it again, even in a new process, must never double-apply or regress anything.

## 2. Core concepts

| Concept | Meaning here |
|---|---|
| **Idempotency key** | `delivery_id`. Seen before = don't act twice. |
| **Canonical payload** | `{tenant, finding_id, version, status}` after trimming. Used to tell an identical redelivery from a conflicting reuse of an ID. |
| **Monotonic version** | A finding's version only goes up. Older events never overwrite newer ones. |
| **Durable state** | A JSON file, so a second process remembers the first. |
| **Atomic write** | The state file is never left half-written. |

## 3. Requirements breakdown

**Input validation (per delivery)**

| Field | Rule |
|---|---|
| `delivery_id`, `tenant`, `finding_id` | Non-empty strings after trimming |
| `version` | Positive integer, **not a boolean** |
| `status` | Exactly `open` or `resolved` (case-sensitive) |
| Tenant | Must equal the CLI `--tenant` |

Invalid or foreign-tenant rows are **rejected and must not reserve their `delivery_id`**.

**State file**

| Situation | Behavior |
|---|---|
| File absent | Empty state for the chosen tenant |
| Malformed, schema-invalid, or wrong tenant | Whole request fails, exit 2, file **untouched** |
| Valid | Has `tenant`, `deliveries` (id → payload), `findings` (id → `{version, status}`) |

**Per-row decision order** (rows are processed in order, and earlier rows affect later ones)

| Step | Condition | Outcome |
|---|---|---|
| 1 | Invalid or foreign tenant | `rejected` (nothing stored) |
| 2 | `delivery_id` known, same payload | `duplicate` |
| 3 | `delivery_id` known, different payload | `rejected` (delivery conflict) |
| 4 | New ID, finding absent or version higher | `applied`, update finding |
| 5 | New ID, version lower | `stale` |
| 6 | New ID, same version, same status | `redundant` |
| 7 | New ID, same version, different status | `rejected` (version conflict) |

Steps 2 and 3 never touch findings. Steps 4–7 **always store the new delivery**, even the stale and rejected ones.

**Output (stdout JSON)**: `results` (one-based `row`, `delivery_id`, `outcome`, `reason`), `counts` (all five outcomes, including zeros), and `findings`.

**Exit codes**

| Code | When |
|---|---|
| 0 | Valid request, even if some rows were rejected, and even with empty `deliveries` |
| 2 | Fatal problems: bad input or state, tenant mismatch, write failure |

## 4. What's expected from you

| Deliverable | Notes |
|---|---|
| Working `app.py` | Keep the documented CLI options |
| Tests | Replace the placeholder test (keep the help and file-error checks). Use temp state paths. Include one boundary case you invent and one failure you caught and fixed. |
| Run guide | Exact commands plus sample outputs |
| Decision log | Priorities, deferrals, one obstacle, one refinement, known limits |
| AI-use note | One real accepted, corrected, or rejected output |
| Walkthrough | 3–5 min video or equivalent text |

Scoring: usable result 40, verification 25, prioritization 20, communication 15. The core alone can earn full marks, and the stretch is optional.

## 5. Your built-in answer key

| Run | Expected counts |
|---|---|
| Primary, fresh state | applied 3, duplicate 1, stale 1, redundant 0, rejected 4 |
| Primary again, same state | applied 0, duplicate 6, stale 0, redundant 0, rejected 3 |
| Secondary, same state, new process | applied 2, redundant 1, no rejections |

Hand-trace primary before coding. For example, `d1` appears three times in a row: the first is new, the second is the identical repeat, and the third reuses the ID with a different status. Classify those, then do `d2` through `d7` yourself. Two rows deserve extra attention:

- **`d7`** shows why "store even if rejected" matters. Check what happens to it on the second run.
- **`d4` and `d5`** show why invalid rows must *not* reserve IDs. Compare how they behave across runs 1 and 2.

If your hand trace doesn't hit the counts above, you've misread a rule. That's far cheaper to find on paper than in code.

## 6. Edge cases to think through

| Edge case | Question to settle |
|---|---|
| `version: true` | Python treats `True` as an integer. How do you exclude it? |
| `version: 2.0` or `"2"` | Valid? The README says positive integer, so decide and document. |
| `" open "` vs `"open"` | Trim first, then compare. Which payload do you store? |
| `"Open"`, `"OPEN"` | Case-sensitive, so invalid. |
| Same ID twice **within one run** | State must update as you go, not once at the end. |
| Foreign-tenant row | Rejected, and the output must not leak its payload beyond row, ID, reason. |
| Foreign row reusing a stored ID | Which check wins? Settle your order and keep it consistent. |
| CLI tenant ≠ file `tenant` | Whole-request failure or per-row rejection? README says "must match", so decide and document. |
| `deliveries` missing or not a list; a row that isn't an object | Fatal vs per-row? Decide deliberately. |
| `deliveries: []` | Success, all counts zero, valid output. |
| State has the wrong tenant or a wrong shape | Exit 2, bytes unchanged. |
| State write fails (e.g. unwritable directory) | Exit 2 with a clear message, old state preserved. |
| `--state` pointed at the input file | Must never modify inputs. |
| Reason strings | Each rejection should say *why* (invalid field, conflict, foreign tenant). |

## 7. Suggested approach

| Step | Action | Checkpoint |
|---|---|---|
| 1 | Run the starter, the smoke tests, and the placeholder command. | You see exit 3 and the 4 passing tests. |
| 2 | Hand-trace both fixtures on paper with a table of row, state before, outcome, state after. | Your counts match the README. |
| 3 | Design your pure logic: validation, normalization, and a function mapping (row, state) → (outcome, new state). Keep file I/O separate. | You can describe each piece in one sentence. |
| 4 | Do state loading and validation first. | Absent, malformed, and wrong-tenant states all behave correctly. |
| 5 | Implement the decision order from section 3. | Primary fresh run gives 3/1/1/0/4. |
| 6 | Add the atomic save (temp file in the same directory, then replace), only after a fully valid request. | A second run reproduces 0/6/0/0/3. |
| 7 | Run secondary in a fresh process. | You get 2/0/0/1/0. |
| 8 | Write tests, each asserting specific results rather than "it ran". | See below. |
| 9 | Write the docs, log, and AI note as you go, not at the end. | Evidence references real row numbers and IDs. |

**Tests worth writing**

- The three-run sequence with exact counts, using a temp state path.
- Malformed state: the exit code is 2 and the file's bytes are identical afterward.
- A boundary case of your own (boolean version, whitespace, empty deliveries, same ID twice in one batch).
- A write failure that preserves the previous state.
- Foreign payloads absent from the output.
- A bug you catch while testing, fixed, with a regression test.

## 8. Common traps

| Trap | Why it bites |
|---|---|
| Updating state only after the loop | Within-batch duplicates are missed. |
| Storing only applied deliveries | Breaks the second run (`d7`, `d2`). |
| Storing invalid rows | Breaks `d4`/`d5` on replay. |
| Checking version before checking the delivery ID | Wrong outcome precedence. |
| Writing state before the request is known to be valid | Corrupts state on a bad input. |
| Omitting zero counts | The spec requires all five outcomes. |
| Over-building (HTTP server, database, framework) | Explicitly out of scope, and it costs prioritization points. |

## 9. Before you start

Write down your answers to these in the decision log first. They are the "assumptions" the README asks you to state:

1. Is tenant mismatch fatal or per-row?
2. Is a float like `2.0` a valid version?
3. Which check runs first when a row is both foreign-tenant *and* a known ID?

When you have a trace table or a first draft, send it and I'll review it against the rules without writing it for you.