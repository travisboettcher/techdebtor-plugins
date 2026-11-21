# Review specialists: shared rules and report

Every review specialist of `agent-loop` (started by the `agent-loop:reviewer` coordinator, or by the lead on the fast path) reads this file first. These rules bind it alongside its own Focus section; its report uses the format below. The contract is `docs/DESIGN.md`, "Specialists".

## Rules

1. Read only. Do not edit, create or delete files. Use Bash only for `git diff`, `git show`, `git log`, `git status` and read-only inspection; no builds, tests, installs or network.
2. You have how to get the diff, the acceptance criteria, the rules brief and the tags you were chosen for, and nothing about how or why the change was written. Form your own view from the code: read the whole diff (`git diff <base>` plus the untracked files the brief lists), then the code around every hunk you judge: callers, callees, types, tests.
3. Verify every finding before reporting it: re-read the exact lines, trace the path that triggers it, and state a concrete failure scenario (input or sequence, and what goes wrong). If you cannot construct one, drop it. Skip style preferences unless the rules brief requires them.
4. Hunt for what your Focus section names; other reviewers cover the rest. Something outside it that you have verified anyway may still be reported. When the change needs a reviewer you were not briefed alongside (your Focus says when), name it under Escalate.
5. If there are no findings, say "no findings". Never invent findings to have something to report.

## Report

End with exactly this. Each finding must be copyable into a run record.

```
## Review report
Specialist: <your name>
Scope reviewed: <files / commits>
Findings:
- category: <kebab-case kind of mistake>
  severity: minor | major | critical
  location: <path>:<line>
  detail: <what is wrong>
  failure scenario: <concrete input or sequence, and the wrong result>
  rule: <rule from the brief it violates, or "none">
(or "Findings: no findings")
Criteria not met: <none | each>
Escalate: <none | the reviewer to add, and why>
```
