# Changelog

## Unreleased

- Lead: acceptance criteria must be testable (EARS form recommended), each naming its test or verifier; with none, the lead stops and asks instead of inventing them.
- Lead preflight: a clean tree; a work branch from an up-to-date `origin/<default>`; build, lint and test commands from `CLAUDE.md`, CI and manifests; a baseline test run whose failures are never blamed on the change; generators and their stale-artifact checks, with new files checked against generator globs.
- Lead plan record: approach and rejected alternative, small ordered units, a test plan from the criteria, risks, out of scope, and a branch budget (about 300 changed lines per unit by default, set in the task text), split by behaviour with tests alongside.
- Lead per-unit loop: the new `agent-loop:test-writer` agent writes failing tests from the criteria and interfaces only; the implementer makes them pass; the lead reruns them itself; one commit per unit when commits were asked for. A pre-push gate runs what the project's `CLAUDE.md` requires and reports against the baseline. Never merges or pushes to the default branch.
- Lead decisions: units run one at a time (parallelism belongs to a dispatcher); a local work branch, created with `--no-track`, whenever the run starts on the default branch, and pushes only as `git push -u origin <slug>`; review-round fixes are separate commits naming the unit; one rule for counting rounds, and at most two test-writer retries per unit before asking.
- Tester: a baseline failure with the same signature is reported as PRE-EXISTING; failing differently is a new failure.
- Run records: optional `plan` (the plan record, or a path to it) and `baseline_failures` (each a test ID with a one-line failure signature; bare IDs stay valid); new stages `preflight`, `test-write`, `gate`; `stage: test-write` and `caught_by: test-writer`. Older records stay valid.
- DESIGN.md: the lead's process and the test-writer's isolation limits.
- Category catalog `docs/categories.md`: process, generated-file, measurement, environment, security and contract categories, each with a description, the stage where it is usually made and the cheapest known rule. The lead and the retro reuse its names before inventing new ones; the retro may propose additions as framework-scope proposals.
- Tester: standing measurement checks when the diff touches tests, measurement or test infrastructure (a subset run never beats the full run, coverage only inside a test body, order independence, distrust of mass failures, the real client's identity, no silent allowlists, new checks opt-in and report-only first), and run hygiene on every run (`bash -c` for multi-step commands, clean up after an aborted heavy run, never rerun until green). A check the data cannot settle is UNVERIFIED, never settled by changing configuration; opt-in gives way when a criterion asks for a blocking check; "no slower" is measured against the baseline wall time the lead notes at preflight. The lead passes it the base commit and that time. DESIGN.md lists the invariants and their categories; the catalog gains `silent-allowlist` and `new-check-not-opt-in`.
- Gates for `skipped-independent-review` and `skipped-plan-approval`: the new `scripts/record_gate.py` (standard library, read-only). `fingerprint` hashes the change since the run's base (tracked diff plus untracked files); the lead records it as `reviewed_diff` when it briefs the reviewer. `check` fails a run record whose change no longer matches `reviewed_diff` (or, without one, has no review after the last change), that lacks `plan_approved`, has `n/a` when approval was required, or has run commits authored before the approval (merges and trunk commits excluded). Exit codes tell the lead what to do: 1 review again, 3 stop and report, 2 cannot check. Plan approval is always the human's answer; in a delegated run the delegator relays it. Run records gain `plan_approved`, `base`, `trunk` and `reviewed_diff`; older records stay valid.

## 0.1.1

- Run records: `caught_by` gains `implementer` (a downstream agent caught a plan or contract defect) and `lead` (the lead caught an agent's mistake); `self` now means only the stage that made the mistake caught it later.
- Reviewer: a standing least-privilege check on any change to `allowed-tools`, agent `tools`, `settings.json` permissions or hooks, or CI tokens (findings: `over-broad-pre-approval`).
- Lead: steps that handle untrusted input or are security-sensitive carry an adversarial input list and a must-not-match list as acceptance criteria, passed to every agent.
- Tester: times any new or changed regex over untrusted input on 100-200 KB adversarial strings; over about a second is a `regex-performance` FAIL.
- CI for the plugin's tests and manifests.

## 0.1.0

- Initial release: `/agent-loop:lead` (implementer, tester and reviewer agents, run records) and `/agent-loop:retro` (transcript and run-record miner, promotion ladder, rules ledger, human gate).
