# Writing a `check`-rung rule (a verify skill)

A `check` is the right rung when the category recurred with an instruction in place, deciding a violation takes judgment (reading the change and its context), and that judgment can be written as steps anyone would apply the same way. If the tool call alone shows the mistake, write a hook instead (`hooks.md`); if the mistake is in the code's behaviour, a test. The contract is `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`, "Verify skills"; a filled-in example is `${CLAUDE_PLUGIN_ROOT}/docs/examples/verify-doc-drift/SKILL.md`.

## Where

Project scope: `<repo>/.claude/skills/verify-<category>/SKILL.md`, on the `retro/` branch with its ledger entry, in one commit. User scope: `~/.claude/skills/verify-<category>/SKILL.md`, shown as a diff and written only after the human says yes. One skill per category: a second rule for the same category is a rewrite of the first.

## Template

Fill every `<...>`. Keep `allowed-tools` to this list or less: no `Write`, `Edit`, wildcard Bash entry or network tool, so it passes the reviewer's least-privilege check. Drop `paths` only when the rule cannot be tied to file globs.

```markdown
---
name: verify-<category>
description: Checks that <the rule, in one sentence>. Use when <the files or kinds of change it applies to>, before reporting the change done.
argument-hint: "[files to check]"
paths:
  - "<glob of the files it applies to>"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash(git diff --name-only HEAD)
  - Bash(git status --porcelain)
---

# Verify: <category>

Rule: <what must hold, and why: one or two sentences, paraphrased from the evidence>.

This skill reports. It never edits a file; fixes go back to whoever made the change.

## Input

The files to check, as named by the caller (`$ARGUMENTS`). With none named, the uncommitted changes: `git diff --name-only HEAD`, plus the untracked files that `git status --porcelain` lists with `??`.

## Procedure

1. <Which of those files the rule applies to.>
2. <What to read in each: the change itself, its callers, the matching file elsewhere.>
3. <What counts as a violation, and what looks like one but is not.>

## Output

One line per violation, `path:line: <what is wrong and what the rule expects>`, and nothing else before the verdict. Then one final line: `PASS` when there are no violations, otherwise `FAIL`.
```

## Before committing

- Follow the procedure once yourself, read-only, over a few files it applies to (ideally the ones from the evidence), and put the result (the files, the violation count and the verdict) in the commit message. A check that flags most of the correct files it reads is too broad: sharpen the steps.
- The ledger entry: `rung: check`, `location: ".claude/skills/verify-<category>/SKILL.md"` (or the `~/.claude/...` path for user scope).
