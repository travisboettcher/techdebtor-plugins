# Changelog

## 0.1.1

- Run records: `caught_by` gains `implementer` (a downstream agent caught a plan or contract defect) and `lead` (the lead caught an agent's mistake); `self` now means only the stage that made the mistake caught it later.
- Reviewer: a standing least-privilege check on any change to `allowed-tools`, agent `tools`, `settings.json` permissions or hooks, or CI tokens (findings: `over-broad-pre-approval`).
- Lead: steps that handle untrusted input or are security-sensitive carry an adversarial input list and a must-not-match list as acceptance criteria, passed to every agent.
- Tester: times any new or changed regex over untrusted input on 100-200 KB adversarial strings; over about a second is a `regex-performance` FAIL.
- CI for the plugin's tests and manifests.

## 0.1.0

- Initial release: `/agent-loop:lead` (implementer, tester and reviewer agents, run records) and `/agent-loop:retro` (transcript and run-record miner, promotion ladder, rules ledger, human gate).
