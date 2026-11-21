---
name: verify-doc-drift
description: Checks that every other description of a changed user-facing behaviour (an option, a default, an environment variable, an exit code, an output format) still matches the change. Use when a change alters user-facing behaviour, before reporting it done.
argument-hint: "[base commit or files to check]"
paths:
  - "src/**"
  - "lib/**"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash(git status --porcelain)
---

# Verify: doc-drift

A worked example of a `check`-rung rule, as `/agent-loop:retro` would write it into a project's `.claude/skills/verify-doc-drift/SKILL.md`. Its ledger entry has `category: doc-drift`, `rung: check` and `location: ".claude/skills/verify-doc-drift/SKILL.md"`. Adjust `paths` to where the project defines user-facing behaviour.

Rule: when a change alters a user-facing behaviour, every other place that describes it says the same thing, in the same change.

This skill reports. It never edits a file; fixes go back to whoever made the change.

## Input

The change since a base commit: `git diff --name-only <base>`, plus the untracked files that `git status --porcelain` lists with `??`. `<base>` is the base commit the caller names (the `/agent-loop:lead` check runner passes the run's base; `$ARGUMENTS` may also name it, or the files to check); if none, `git merge-base HEAD origin/<default>`. Never diff against `HEAD` alone: once the work is committed that diff is empty and the check would pass without seeing anything. Run on its own, `git diff` asks for permission: a pre-approval wide enough for it (`git diff *`) would also admit `--output=<file>`, which writes.

## Procedure

1. Keep only the files that define user-facing behaviour: argument parsing and help text, configuration loading and defaults, environment variables, exit codes, output formats.
2. For each, read the change itself, not only the file: `git diff <base> -- <file>` (an untracked file is all new).
3. List every behaviour the change adds, removes, renames or alters, with its name, its old value or meaning, and its new one. A renamed constant with the same value is not a behaviour change.
4. For each behaviour, search the repository (Grep) for its name, and its old name if renamed, outside the changed lines: README and docs, usage and help strings, examples, configuration templates, comments that state the value, and the changelog.
5. Each place that still states the old name, value or meaning is a violation. History is not: an entry under an earlier, released changelog version stays as it was.
6. If the project keeps a changelog with an unreleased section, a behaviour change without an entry there is a violation, reported at that section's heading.

## Output

One line per violation, and nothing else before the verdict:

```
path:line: says <old>; the change made it <new> (<behaviour>)
```

Then one final line: `PASS` when there are no violations, otherwise `FAIL`.
