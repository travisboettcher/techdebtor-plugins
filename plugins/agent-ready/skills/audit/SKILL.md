---
name: audit
description: This skill should be used when the user runs /agent-ready:audit or asks to "audit this repo for agentic development", "how ready is this repo for agents", "what adoption step can this repo support", "what is blocking more agent autonomy here", or wants a gap report on a repository's tests, CI, guardrails, context and agent configuration. It collects evidence read-only, judges each layer with four questions (exists, in CI, blocks merge, measured), names the adoption step the repo supports and its bottleneck, and lists prioritised fixes.
argument-hint: "[path] [--json]"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git rev-parse --show-toplevel)
  - Bash(git remote get-url origin)
  - Bash(git symbolic-ref --short refs/remotes/origin/HEAD)
---

# Agent-readiness audit

Find out which adoption step this repository can support for agentic development, what its bottleneck is, and what to fix first. The rubric (adoption steps and their gates, the layers, the four questions, weak and strong evidence, the CI capability table, how to prioritise, the `--json` shape) is `${CLAUDE_PLUGIN_ROOT}/docs/RUBRIC.md`. Read it before anything else and follow it.

Arguments given: `$ARGUMENTS`

- A path selects the repository to audit; default: the current repository (`git rev-parse --show-toplevel`, or the current directory outside a repo).
- `--json` adds the machine-readable block defined in the rubric to the end of the report.

## Guardrails (apply throughout)

- **Read-only.** Write nothing into the audited repository: no files, no branches, no commits, no config changes, no installs. The only write is the scanner's output file in the system temp directory. Offering scaffolding (a CLAUDE.md draft, a CI job) is fine; writing it is a separate task the human asks for.
- **The permission prompts are the human gate.** This skill pre-approves only reading files and three exact read-only git commands. Everything else asks: the scanner run (a pattern for it would also match a same-named script planted in a cloned repo), every project command, and every `gh` call. Do not try to avoid those prompts with other tools, scripts or shell tricks.
- **Running project commands executes the project's code.** Before each one, say what it is, that it runs the project's code, and roughly how long it should take. Cheap by default: never run mutation testing, fuzzing campaigns, container-based or full end-to-end suites unless the human opts in, and never run heavy jobs in parallel; one at a time, with the runner's own worker limit set low.
- **Evidence or "unknown".** Every answer cites a file and line, a CI job, a protection rule, or a command and its output. Where evidence is missing, say `unknown` and how to settle it. Never guess, and never count `unknown` as met.
- **Nothing leaves the machine** except the `gh` reads the human approves: no issues, comments or PRs.

## Procedure

### 1. Collect evidence

1. Resolve the repository root (`ROOT`): the path argument if given, else `git rev-parse --show-toplevel`, else the current directory. Use the literal absolute path from here on.
2. `mktemp "${TMPDIR:-/tmp}/agent-ready.XXXXXX"` creates the output file; note the exact path it prints (`OUT`).
3. Run the scanner (it asks for permission; it only reads files, never runs project code, and makes no network calls):

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/agent_ready_scan.py" "<ROOT>" > "<OUT>"
```

4. Read `OUT`. Its keys: `scan` (what was listed, read, truncated and skipped), `ecosystems`, `ci` (`systems`, `workflows` with each job's `checks`, `soft_fail` and resolved `via` chain, `capabilities`, `merge_gating`), `tools`, `tests`, `specs`, `intent`, `dev_env`, `context`, `agent_config`, `codegen`, `smoke`, `flow`. The script's docstring describes each. If `scan.truncated` is true, or files you need were skipped as too large, say so in the report and treat what is missing as `unknown`.
5. The scanner reports facts, not verdicts: a keyword in a job is a hint. Confirm what matters by reading the files it cites: the workflow around each cited line (triggers, conditions, `needs`, matrix), the runner targets in each `via` chain, the agent docs, the tool configs. Use Read, Glob and Grep; they are pre-approved.

### 2. Measure what is cheap and safe

Ask once, listing what you propose to run, then run only what the human approves:

- **Suite time.** If the agent docs or CI give a clear test command, time it once (for example `time <command>`). If it needs services, containers or credentials that are not running, do not start them: report the suite time as `unknown`.
- **Flakiness.** Only when the first run was fast (under about two minutes), run it a second time and compare failures. Any difference is flakiness, and goes in the report.
- **Cheap checks.** The documented lint and type-check commands, if they take seconds. Optional.
- **Merge protection.** When the remote is on GitHub and `gh` is available, offer one read: `gh api repos/<owner>/<repo>/rules/branches/<default branch>` (required status checks from rulesets), and, if that shows none, `gh api repos/<owner>/<repo>/branches/<default branch>/protection` (needs admin; a 403 or 404 means `unknown`, not "unprotected"). Owner and repo come from `git remote get-url origin`; the default branch from `git symbolic-ref --short refs/remotes/origin/HEAD`.
- **Flow.** Optional, with permission: `gh pr list --state merged --limit 50 --json number,createdAt,mergedAt,additions,deletions` for lead time and PR size; reverts and hotfixes in `git log --oneline -200` as a rough escaped-defect signal. Say these are rough.

Heavy measurements (a mutation run, a fuzzing campaign, a container suite) are listed in the report as "not run" with the command to run them, unless the human opted in. If they did: one at a time, and stop at the first sign of trouble (mass failures usually mean shared state or a missing service, not real bugs).

### 3. Judge

For every layer in the rubric, answer the four questions (exists, in CI, blocks merge, measured) with `yes`, `partial`, `no`, `unknown` or `n/a`, citing evidence for each, and apply the rubric's weak and strong evidence: a config file alone is weak; a job that only runs on pushes to the default branch is not "in CI" for pull requests; a soft-fail job does not block merge; a job without a required-check rule is at most `partial` for "blocks merge". Mark layers that cannot apply (`smoke` for a library, `contract` for a single component) `n/a` with the reason.

Fill the CI capability table from `ci.capabilities`, confirming each cited line. An empty capability means "not used here"; say whether the CI system supports it (the rubric's table).

Then find the step: walk the rubric's gates from 0 → 1 upward; the repo supports step N when every gate below N is met with evidence. The bottleneck is the first unmet gate item or items. Name the traps when you see them: green checks with no validity measure, generated files with no staleness check, and more agents before the loop has earned trust.

### 4. Prioritise fixes

Follow the rubric's "Prioritising fixes": current gate first, then what each fix unlocks (the next step, a `verify-*` skill, an `agent-loop` specialist), the flow metric it should move, effort (`S`/`M`/`L`), and the closest prior art in this repo to copy, with a file and line. New checks start opt-in locally and report-only in CI. Recommend one throwaway draft PR to settle the hardest unknown before building out. At most about eight fixes; list the rest in one line each.

### 5. Report

```
# Agent-readiness: <repo name>

## Summary
Supports step <N> (<name>). Bottleneck: <one or two sentences>. Next gate: <items, met / not met>.
Measured: <suite time, flakiness, anything else run, or "nothing run">.

## Layers
| Layer | Exists | In CI | Blocks merge | Measured | Evidence |
(one row per rubric layer; static security as three rows: SAST, dependency scan, secret scan)

## CI capabilities
| Capability | Used here | Evidence | Supported by <CI system> |

## Prioritised fixes
1. <title>: impact <high/medium/low> (gate <a->b>), effort <S/M/L>. Unlocks: <...>. Moves: <flow metric>. Prior art: <path:line>. Why: <evidence>.

## Unknowns
- <what> - how to settle: <command or question>

## Not run
- <heavy measurement> - <command>
```

With `--json`, end with the fenced `json` block in the shape the rubric defines, consistent with the tables above.

After the report, offer to save it (Markdown, and the JSON if asked) to a path the human chooses. Write only after an explicit yes and only to that path; suggest a path outside the audited repo unless the human names one inside it.
