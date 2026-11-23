# Changelog

## 0.1.1 (2026-11-22)

- RUBRIC.md: the reasons given for the contract and codegen layers no longer state unmeasured claims about where bugs and CI failures come from.

## 0.1.0

- Initial release: `/agent-ready:audit [path] [--json]`, the rubric (`docs/RUBRIC.md`: adoption steps and gates, layers, the four questions, CI capability table, prioritising fixes, the JSON shape) and `scripts/agent_ready_scan.py`, a read-only evidence scanner (standard library only).
- Behavioural evals for `claude plugin eval` in `evals/`: `audit-report` (smoke: layers with evidence or `unknown`, the adoption step and bottleneck, and never reading a symlink that leaves the repository) and `audit-json` (full: the `--json` block's shape, layer ids and enums), on a scaffolded fixture repository. `pytest.ini` keeps the fixtures' own test files out of the plugin's test run.
