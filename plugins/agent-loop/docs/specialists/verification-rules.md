# Verification specialists: shared rules and report

Every verification specialist of `agent-loop` (started by the `agent-loop:tester` coordinator, or by the lead on the fast path) reads this file first. These rules bind it alongside its own Job section; its report uses the format below. The contract is `docs/DESIGN.md`, "Specialists".

## Rules

1. Change nothing in the repository: no edits, no new files, no fixes, not even trivial ones. Scratch files go in a temporary directory outside it (`mktemp -d`), removed when you finish; `git status --porcelain` must read the same at the end as at the start.
2. Never install anything (packages, tools, browsers, databases) or change configuration to make a check run. A missing tool, spec, credential or service makes the check BLOCKED, naming exactly what is missing.
3. Heavy jobs (full suites, builds, fuzzing, mutation, system or performance runs) one at a time, never in parallel. Multi-step commands as `bash -c '...'`, never in the interactive shell. Wrap every long command in `timeout`, within your time limit if the brief gives one. After an aborted or stopped run, remove what it started (containers, processes, temporary databases, worktrees), check nothing is left, and report what you could not remove.
4. The change is everything since the brief's `<base>`: `git diff <base>` plus untracked files (`git status --porcelain`). Never a hard-coded branch, never `HEAD` alone.
5. A flaky result is a finding: rerun once and report both outcomes. Never rerun until green.
6. Follow the rules brief, and never put secrets in your output.

## Report

End with exactly this. Quote evidence trimmed to what matters.

```
## Verification report
Specialist: <your name>
Checks:
- `<command or check>`: PASS | FAIL | PRE-EXISTING | BLOCKED | UNVERIFIED
  <for anything but PASS: the failing assertion, error, input or numbers; for BLOCKED, what is missing>
Wall time: <minutes, all checks together>
Findings:
- category: <kebab-case, from the categories in your brief where one fits>
  severity: minor | major | critical
  location: <path>:<line>, or the command
  detail: <what failed, with a reproduction>
(or "Findings: none")
```
