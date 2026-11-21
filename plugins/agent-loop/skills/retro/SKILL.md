---
name: retro
description: This skill should be used when the user runs /agent-loop:retro or asks to "run a retro", "do a retrospective", "learn from recent sessions", "check whether our rules are working", "find recurring mistakes", or "write a run record for this session" (/agent-loop:retro --record). It mines run records and Claude Code transcripts for corrections, denials and recurring findings, verifies every rule in the rules ledger, and proposes at most a handful of new or changed rules behind a human gate.
argument-hint: "[window, e.g. 14d | 2026-11-01] [--record]"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(python3 */scripts/retro_mine.py *)
  - Bash(python3 "*/scripts/retro_mine.py" *)
  - Bash(git status)
  - Bash(git status *)
  - Bash(git log *)
  - Bash(git diff *)
  - Bash(git show *)
  - Bash(git rev-parse *)
  - Bash(git symbolic-ref --short refs/remotes/origin/HEAD)
  - Bash(git worktree list)
  - Bash(git worktree list *)
  - Bash(git branch --list *)
  - Bash(date +%F)
---

# Retro

Close the loop: find what keeps going wrong, turn the recurring part into the cheapest rule that stops it, and check that earlier rules actually worked. The contract (run record and ledger formats, the ladder, verdicts, scope, the human gate) is `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`. Read it before anything else and follow it exactly. The model does not learn; the scaffolding does, and a rule only counts as an improvement once a later retro shows its category stopped recurring.

Arguments given: `$ARGUMENTS`

- A window (`14d`, `2w`, `12h`, an ISO date) sets `--since`; default `30d`.
- `--record` means: write a run record for the current session (see "Recording a session") and stop, unless a retro was also asked for.

## Guardrails (apply throughout)

- **No raw transcript text anywhere.** Evidence in proposals, commits, ledger entries and records is either paraphrased or copied from the miner's already-redacted `excerpt` / `preceding_action` fields. Evidence in `framework-proposals.md` is paraphrased only: never copy an `excerpt` there, since it is meant to leave the project. Never open `~/.claude/projects` transcripts directly.
- **The permission prompts are the human gate.** This skill pre-approves only reading: files, the miner and read-only git. Every file write, `git worktree add`, commit or push asks the human first. Do not try to avoid those prompts (no other tools, scripts or shell tricks to write files or run git).
- **At most ~5 proposals per retro**, ordered by recurrence x severity. Everything else is listed under "not proposed".
- **Prefer deleting or merging rules over adding them.** A rewrite of an unclear rule beats a second rule for the same category.
- **Never on the default branch, never pushed.** Project changes go on a `retro/YYYY-MM-DD` branch; user changes wait for an explicit yes.
- Nothing leaves the machine: no issues filed, no PRs opened, no network calls.

## Procedure

### 1. Mine

1. `git rev-parse --show-toplevel` gives the project root (`ROOT`; outside a repo, use the current directory).
2. `mktemp "${TMPDIR:-/tmp}/retro-mine.XXXXXX"` creates the output file; note the exact path it prints (`OUT`). Use that one path for the rest of the retro.
3. Run the miner into it, with the literal paths:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/retro_mine.py" --root "<ROOT>" --since 30d --max-signals 200 > "<OUT>"
```

Read `OUT`. Keys: `window` (the windows used, below), `transcripts` (scan stats), `signal_counts` and `signals` (type `correction` | `interrupt` | `user_denial` | `policy_denial` | `revert`, each with `session_id`, `timestamp`, `excerpt`, `preceding_action`, `cues`), `run_records` (records in the requested window plus `parse_errors`), `category_counts`, and `ledgers.project` / `ledgers.user` (each rule with `occurrences_since`, `last_occurrence`, `records_since_added`, `days_since_added`, `last_verdict`, or an `error` if its `added` date is invalid). Also read the ledger files themselves and the existing rules they point at (`location`). Without run records (no `lead` plugin), work from signals alone.

Windows (`window`): the miner reads every run record in every worktree of the project whatever `--since` says, so each rule's `occurrences_since` already covers all records since its `added` date; only `category_counts` and `run_records.records` are limited to the requested window (`window.since`). Transcript signals reach further back: to the `added` date of the oldest ledger rule, at most 90 days (`window.transcripts_since`, with the reason in `window.transcripts_extended_for`). Signals older than `window.since` are there to verify ledger rules (step 2); do not count them toward new proposals (steps 3-4).

Signals are heuristics. Discard false positives (a "no" that answered a question, a denial that was just caution) before counting.

### 2. Verify every ledger rule

For each rule in both ledgers, add to the run-record occurrences (`occurrences_since`) any signals that clearly belong to the rule's category and are dated after `added`. For a rule added more than 90 days ago, signals only cover the last 90 days; say so when reporting it. A rule with an `error` is reported as unverifiable, with the error. Then:

| Verdict | When | Action |
|---|---|---|
| `working` | no occurrence since `added` | keep |
| `recurring` | one or more | propose the next rung up, or a rewrite if the rule is unclear or the agent could not have seen it |
| `dormant` | no occurrence, `days_since_added` >= 90, and no relevant work in 90 days (no record or signal touching what the rule guards) | propose retiring it |

Also confirm the rule still exists at `location`; a missing rule is reported, not silently re-added. Prepare one `history` entry per rule (`date`, `occurrences_since`, `verdict`); these go in the proposal commit, not on the default branch.

### 3. Cluster

Group signals and record findings into categories. Reuse a category from the ledger or earlier records whenever one fits; invent a kebab-case one only when nothing does. Count recurrences per category (distinct sessions or records, not repeated messages within one exchange). Assign a severity: `critical` for data loss, secrets, destructive or irreversible actions, anything pushed or deployed wrongly; `major` for rework or a wrong result; `minor` otherwise. A category seen once and not critical stays a note: list it, propose nothing.

### 4. Choose rung and scope

Rank candidates by recurrence x severity (critical = 3, major = 2, minor = 1) and keep the top ~5 (verdict-driven changes from step 2 count toward the five).

Rung (the ladder):
- `instruction`: seen twice, or once at `critical`. Write the actual text and name the file (CLAUDE.md, a skill, memory). One or two sentences, phrased as what to do, with the reason.
- `hook`: it recurs after an instruction exists **and** a script can check it mechanically. Write the actual hook config and script (see `${CLAUDE_SKILL_DIR}/references/hooks.md`).
- `test`: the mistake is about the code's behaviour, not process. Write the actual test in the project's framework.

Scope:
- `project`: only makes sense in this repo (its layout, tools, conventions).
- `user`: the human's preferences or environment across repos (`~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills`, memory).
- `framework`: would help anyone using these plugins (a missing reviewer check, a better lead prompt).

Each new rule gets a ledger entry: `id` (`<category>-<n>`), `category`, `rung`, `scope`, `location`, `summary`, `added` (today), `baseline` (occurrences of the category in this window before the rule), `history: []`.

### 5. Human gate

**Project scope.** Never touch the user's checkout or the default branch. Find the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, else `main` / `master`), then work in a temporary worktree:

```bash
BR=retro/$(date +%F)            # add -2, -3 ... if it exists
WT=$(mktemp -d /tmp/retro-wt-XXXXXX)
git worktree add -b "$BR" "$WT" <default-branch>
```

In `$WT`: first one commit `retro: verify ledger rules` with the history entries (and any retirements: remove the rule's text and its ledger entry together). Then **one commit per new or escalated rule**, each containing the rule (instruction text, hook config + script, or test) **and** its ledger entry in `.claude/rules-ledger.yml` (create it as `schema: 1` / `rules:` if missing). Commit messages: `retro: <category> -> <rung>` with a two-line paraphrased rationale (counts, not quotes). Run the project's tests if a test or hook was added. Then `git worktree remove "$WT"`; the branch stays. Do not push. Each write and git command here asks the human for permission; that is intended.

**User scope.** Show each change as a unified diff against the current file (including the `~/.claude/rules-ledger.yml` entry) and ask. Apply only the ones the human approves, exactly as shown.

**Framework scope.** Append to `<repo>/.claude/runs/framework-proposals.md` (create it if missing): a dated heading, the category, count and severity, the proposed change to the plugin, and paraphrased evidence only (no `excerpt` text, quoted or not). Never file it anywhere.

### 6. Report

Finish with:

1. **Rules verified**: table of id, category, occurrences since added, verdict, action.
2. **Proposals**: table of category, count, severity, rung, scope, where (branch + commit, diff awaiting yes, or framework-proposals.md).
3. **Not proposed**: one-off notes, false positives discarded, candidates cut by the five-proposal limit, and why.
4. How to review: `git log -p <default>..retro/YYYY-MM-DD`, then merge or delete the branch.

Delete the miner output at the end: `rm -f "<OUT>"` with the exact path `mktemp` printed. Never a glob: other retros may be running.

## Recording a session (`--record`)

Write `<repo>/.claude/runs/YYYY-MM-DD-<slug>.yml` for the current session in the run-record shape from `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md` (`schema: 1`, `date`, `task`, `repo`, `outcome`, `rounds`, `stages`, `findings`, optional `rejected`, `notes`). Findings are only things that went wrong and were caught (by a stage, a hook, CI or the human), each with a reused category where one fits. No secrets, private hostnames, personal data or quotes from the conversation; paraphrase. Show the file to the human after writing it. If `.claude/runs/` is not gitignored and the project has not decided, mention that committing or ignoring `.claude/runs/` is the project's choice.
