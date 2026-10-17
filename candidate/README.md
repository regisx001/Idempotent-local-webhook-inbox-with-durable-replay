# Idempotent local webhook inbox with durable replay

This is one Software Engineer Intern assessment with a **24-hour** window. Your recruiter assigns one exercise, never all five. Your 24 hours start when you click **Start** on the link in your invitation email; the exercise zip becomes available at that moment. Send your submission back within 24 hours of clicking Start. You are not expected to work for the full 24 hours: organize your own working time and breaks within the window. There are no surprise messages or overnight availability requirements, and hours worked are not scored. Follow-through and verification matter more than hours or volume.

A fictional integration redelivers finding status events after a timeout. Build a local inbox that stores idempotency keys, ignores stale versions, and survives another CLI process. Delivery order can be wrong. All events and state are local synthetic files; no HTTP server or credentials are needed.

All companies, tenants, assets and product behavior here are **fictional assessment facts**. The supplied fixtures are the authoritative universe. Outside research is optional and cannot affect marks. Do not contact real systems, send real messages, publish, or use production credentials.

## Supplied inputs and setup

You need basic Python, JSON, CLI use, tests, and familiarity with durable idempotency, canonical payload comparison, monotonic versions, local atomic writes, and replay diagnostics. Python **3.10 or later**, its standard library, and any local editor are sufficient; no packages, accounts, paid tools, web access or company framework are needed.

- [Starter CLI](app.py): argument parsing and safe JSON loading, with the feature deliberately unfinished.
- [Primary fixture](inputs/primary.json): main business cases, including deliberate inconsistencies.
- [Second fixture](inputs/secondary.json): use it to demonstrate the feature is reusable.
- [Malformed input](inputs/malformed-input.txt): deliberately truncated JSON, despite its .txt extension; use for error handling.
- [Starter smoke checks](tests/app_test.py): four infrastructure checks, **not feature acceptance tests**.

From the exported `candidate/` directory:

```sh
python3 --version
python3 app.py --help
python3 -m unittest discover -s tests -p '*_test.py' -v
python3 app.py --input inputs/primary.json
```

The initial smoke suite should pass. The last command should print `STARTER: implement ingest_events` to stderr, return **3**, and produce no stdout. This is intentional, not a setup failure. The starter neither solves the feature nor provides a completed output. Replace the placeholder behavior and replace its smoke assertion with feature assertions; keep the help/file-error checks. You may restructure code, but preserve documented CLI options and make the README run commands accurate.

## Core task and observable acceptance criteria

Build a usable feature implementing the following contract. Use JSON on stdout for successful runs, readable diagnostics on stderr for fatal errors, and the documented exit codes. Explain any assumptions without silently changing the rules.

- Input has `tenant` and `deliveries`; CLI tenant must match. Each delivery needs nonempty strings delivery_id/tenant/finding_id, positive integer version (not boolean), and status open/resolved. Trim strings; membership is case-sensitive. Invalid or foreign-tenant deliveries produce rejected diagnostics and must not reserve an idempotency key.
- State JSON must contain `tenant`, `deliveries` as a mapping from delivery_id to canonical payload `{tenant,finding_id,version,status}`, and `findings` as a mapping from finding_id to `{version,status}`. An absent --state file means empty state for the chosen tenant. Malformed/schema-invalid/wrong-tenant state fails the whole request with exit 2 without overwriting it.
- Process delivery rows in order. A previously stored delivery_id with the same canonical payload is duplicate; a different payload is rejected as delivery conflict. These never change findings.
- A new valid delivery_id is stored even when its version is stale or conflicting. If its version exceeds the current finding version (or the finding is absent), update finding and classify applied. Lower version: stale. Equal version with same status: redundant. Equal version with different status: rejected as version conflict. Never decrease a version.
- Output `results` with one-based row, delivery_id, outcome (applied/duplicate/stale/redundant/rejected) and reason; `counts` for all five outcomes; and `findings` current state. Do not expose foreign payloads beyond row, delivery_id and reason.
- Save the complete updated state only after processing a valid request. Use an atomic local replacement (temporary file in same directory + replace is enough). Report write failures clearly with exit 2. Preserve the previous state if writing fails; no concurrency or crash-injection framework is required.
- Empty deliveries succeed. Valid requests with rejected rows exit 0. Input files never change; do not use the input path as --state. A second process using saved state must obey the same idempotency rules. Tests should use a temporary state path.

Fresh primary run must produce applied 3, duplicate 1, stale 1, redundant 0, rejected 4. Repeat primary against saved state: applied 0, duplicate 6, stale 0, redundant 0, rejected 3. Then run secondary in a fresh process on that state: applied 2, redundant 1, no rejections. Test malformed state and ensure prior bytes survive.

Add meaningful automated checks that test results and errors, not just that code runs. Include at least one boundary case you construct, and one failing case you fix or a validation that causes a refinement. A clear, tested core earns full marks. Optional stretch: improve the local developer experience or add a useful extra test; no stretch is necessary. A web service, full framework, database, public deployment, or large architecture is outside the core scope.

After implementing the core, use these exact local verification runs. Choose a new local state path that does not exist before the first command; reuse it for the following commands. The example uses scratch-state.json. Do not delete a real file or reuse unrelated state. The starter does not create this file. Initially every valid fixture invocation returns the documented exit-3 placeholder; after implementation, each should succeed and match the criteria above.

```sh
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
python3 app.py --input inputs/primary.json --tenant north --state scratch-state.json
python3 app.py --input inputs/secondary.json --tenant north --state scratch-state.json
```

## Time and AI use

Plan your own time within the 24-hour window. Prioritize the core contract and leave time for verification instead of adding features.

**AI is allowed and encouraged** for coding, explanation, test generation, critique and optional research. Tool choice is not graded. No AI tool is provided; you may use any AI tool you already have, and no purchase is required. Free/offline tools and completing the exercise without AI are supported. Check AI output against the rules, input rows and executed tests. Submit a short AI-use note with one concrete accepted, corrected or rejected output and how you checked it; if you did not use AI, state that. Do not invent an AI failure or share complete prompt histories, private account access, or secrets.

## Submission

Submit an archive or repository containing runnable source, tests, the supplied inputs, and:

1. A short run guide with exact commands for both fixtures and the meaningful checks; include representative outputs or assertions with input row/key references.
2. A concise decision/work log: priorities and what you deferred; one obstacle and response; one validation/refinement; known limits and next step. Cite fixture source IDs, event IDs, finding keys or row numbers as evidence.
3. The AI-use note described above.
4. A 3–5 minute walkthrough recording **or equivalent accessible text** explaining the core workflow, one edge case, and evidence of execution.

You do not need a public repository, deployment, PDF or proprietary tools. Document incomplete behavior honestly. Do not submit only a design or report: the runnable feature and reproducible tests are the primary deliverables.

Published scoring: **usable result 40, accuracy/verification 25, prioritization 20, communication/handoff 15**. Full marks are available on the core alone. Tool choice, AI-detector judgments, prose polish, hours worked and sheer output volume are not scored.
