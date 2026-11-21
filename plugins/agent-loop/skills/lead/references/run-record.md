# Run record: shape and rules

Read by `/agent-loop:lead` at step 9. The authoritative format is `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`; this is its shape:

```yaml
schema: 1
date: YYYY-MM-DD
task: "One-line description of the task"
repo: <basename of the git root>
outcome: completed            # completed | merged | reworked | abandoned | in-progress
rounds: 1                     # implement→test→review rounds run
stages: [preflight, plan, test-write, implement, test, review, gate]   # what actually ran, in order (repeat per unit and round)
plan:                         # the plan record from step 3 (or a path to it)
  approach: "..."
  alternative: "... rejected because ..."
  units: ["..."]
  risks: ["..."]
  out_of_scope: ["..."]
  branch_budget: 300
plan_approved: "2026-11-21T14:05:00+00:00"   # `date -Iseconds` when the human approved the plan; n/a when approval was not required
base: <sha>                   # <base> from preflight
trunk: origin/main            # <trunk> from preflight
reviewed_diff: "sha256:..."   # the fingerprint taken when you briefed the last review
baseline_failures:            # tests failing on the base before any change; [] when none
  - test: "path::test_name"
    signature: "ExceptionType: one redacted line"
findings:
  - stage: implement          # where the mistake was made: plan | test-write | implement | test | review
    category: doc-drift       # from the catalog where one fits
    severity: major           # minor | major | critical
    detail: "What went wrong, in one or two sentences."
    caught_by: reviewer       # test-writer | tester | reviewer | implementer | lead | human | ci | hook | self
    fixed: true
rejected:                     # optional: reported findings you showed were wrong
  - stage: review             # here: the stage that reported the wrong finding
    category: scope-mismatch
    reason: "Why it was wrong."
notes: "Optional free text."
```

Rules for the record:
- A finding is something that went wrong and was caught. Not a summary of the work. A clean run has `findings: []`.
- Record every finding from every stage and round: test-writer and tester failures, confirmed review findings, problems the human pointed out, deviations you had to correct, and mistakes you made yourself (a wrong plan, a missing criterion, a bad brief, a missed preflight check). Do not soften or omit them.
- `stage` is where the mistake was made, never who caught it; `caught_by` is who caught it. A defect in the change found by anyone is `stage: implement`. A missing or wrong criterion or verifier, a wrong plan, a missed preflight check or a bad brief is `stage: plan`. `stage: test-write` is a wrong test. `caught_by: self` only when the stage that made the mistake caught it later (you, for your own plan); a plan or contract gap an agent reports is `caught_by` that agent (`implementer`, `test-writer`), and an agent's mistake you catch (a deviation, a misreported result, a test that cannot fail) is `caught_by: lead`. `stage: test` / `stage: review` only for mistakes the tester or reviewer made themselves.
- `stages` lists every stage as it ran, and `reviewed_diff` is the fingerprint you actually took for the last review: `scripts/record_gate.py` checks both. Never add a stage that did not run or a fingerprint you did not take.
- Reuse an existing category (the catalog and the others you listed in step 1) when one fits. Invent a new kebab-case category only when none does; name the kind of mistake, not the incident (`redaction-gap`, not a name for the one token that slipped through).
- `outcome`: `completed` when the run finished, `in-progress` only if it stopped part-way, unless the human has told you the change was merged, reworked or abandoned. Update the record if they tell you later in the session.
- Never put secrets, tokens, private hostnames or personal data in a record.
