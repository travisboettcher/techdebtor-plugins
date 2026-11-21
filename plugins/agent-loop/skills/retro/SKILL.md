---
name: retro
description: This skill should be used when the user runs /agent-loop:retro or asks to "run a retro", "do a retrospective", "learn from recent sessions", "check whether our rules are working", "find recurring mistakes", or "write a run record for this session" (/agent-loop:retro --record). It mines run records and Claude Code transcripts for corrections, denials and recurring findings, verifies every rule in the rules ledger, and proposes at most a handful of new or changed rules behind a human gate.
argument-hint: "[window, e.g. 14d | 2026-11-01] [--record]"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git status)
  - Bash(git status *)
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
- **The permission prompts are the human gate.** This skill pre-approves only reading: files and a short list of read-only git commands (`git log`, `git diff` and `git show` are not on it, since `--output=<file>` makes them write; they ask). The miner is not pre-approved either: a pattern for it would also match a script of the same name planted in any cloned repo, so running it asks for permission once per retro. Every file write, `git worktree add`, commit or push asks the human first. Do not try to avoid those prompts (no other tools, scripts or shell tricks to write files or run git).
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

Read `OUT`. Keys: `window` (the windows used, below), `transcripts` (scan stats), `signal_counts` and `signals` (type `correction` | `interrupt` | `user_denial` | `policy_denial` | `revert`, each with `session_id`, `timestamp`, `excerpt`, `preceding_action`, `cues`), `run_records` (records in the requested window plus `parse_errors`), `category_counts`, `specialists` (below), and `ledgers.project` / `ledgers.user` (each rule with `superseded_by`, `occurrences_since`, split into `caught_by_rule` and `escaped`, `last_occurrence`, `records_since_added`, `days_since_added`, `last_verdict`, or an `error` if its `added` date is invalid). Also read the ledger files themselves and the existing rules they point at (`location`). Without run records (no `lead` plugin), work from signals alone.

Windows (`window`): the miner reads every run record in every worktree of the project whatever `--since` says, so each rule's `occurrences_since` already covers all records since its `added` date; only `category_counts` and `run_records.records` are limited to the requested window (`window.since`). Transcript signals reach further back: to the `added` date of the oldest ledger rule, at most 90 days (`window.transcripts_since`, with the reason in `window.transcripts_extended_for`). Signals older than `window.since` are there to verify ledger rules (step 2); do not count them toward new proposals (steps 3-4).

`specialists` measures the verification and review specialists from every run record with a `selection`: `selection` (the table's paths, its `retro` thresholds and any `errors` in the project's override), `by_specialist` (per specialist: `runs` that chose it, `findings`, `rejected`, `precision`, `misses` (findings in its own categories, in a run that chose it, that it did not report and that escaped the swarm: caught by the human, CI, a hook or the dispatcher, or in a later round), `miss_rate`, `overlap` (the same, caught by another specialist in the same round), and those counts `by_tag` for the tags that selected it), and `by_tag` (per tag: `runs` and the categories that `escaped`).

Signals are heuristics. Discard false positives (a "no" that answered a question, a denial that was just caution) before counting.

### 2. Verify every ledger rule

For each rule in both ledgers, add to the run-record escapes (`escaped`) any signals that clearly belong to the rule's category and are dated after `added`; a signal is always an escape. `caught_by_rule` counts findings a `hook` or `check` rule caught itself, or a `selection` rule's added specialist reported (for a `change: drop` rule, the findings the swarm still caught): the rule fired, and those never make it `recurring`. For a rule added more than 90 days ago, signals only cover the last 90 days; say so when reporting it. A rule with an `error` is reported as unverifiable, with the error. Then:

| Verdict | When | Action |
|---|---|---|
| `working` | nothing escaped since `added` (catches by the rule itself allowed) | keep; if it catches constantly, note that the instruction upstream may be unclear, but do not escalate |
| `recurring` | one or more escaped | propose the next rung up, or a rewrite if the rule is unclear or the agent could not have seen it; for a `check`, see DESIGN.md "Verify skills" (escalation) |
| `superseded` | the rule has `superseded_by` (a higher-rung rule replaced it) | report it with its counts; never escalate it |
| `dormant` | no occurrence, `days_since_added` >= 90, and no relevant work in 90 days (no record or signal touching what the rule guards) | propose retiring it |

Also confirm the rule still exists at `location`; a missing rule is reported, not silently re-added. Prepare one `history` entry per rule (`date`, `occurrences_since`, `caught_by_rule`, `escaped`, `verdict`); these go in the proposal commit, not on the default branch.

### 3. Cluster

Group signals and record findings into categories. The catalog `${CLAUDE_PLUGIN_ROOT}/docs/categories.md` is the starting vocabulary: reuse a category from it, the ledger or earlier records whenever one fits (its "cheapest known rule" is the first candidate rule for that category); invent a kebab-case one only when nothing does, naming the kind of mistake, not the incident. A new category that recurs and would apply beyond this project may be proposed for the catalog itself, as a framework-scope proposal (step 4). Count recurrences per category (distinct sessions or records, not repeated messages within one exchange). Assign a severity: `critical` for data loss, secrets, destructive or irreversible actions, anything pushed or deployed wrongly; `major` for rework or a wrong result; `minor` otherwise. A category seen once and not critical stays a note: list it, propose nothing.

### 4. Choose rung and scope

Rank candidates by recurrence x severity (critical = 3, major = 2, minor = 1) and keep the top ~5 (verdict-driven changes from step 2 count toward the five).

Rung (the ladder):
- `instruction`: seen twice, or once at `critical`. Write the actual text and name the file (CLAUDE.md, a skill, memory). One or two sentences, phrased as what to do, with the reason.
- `check`: it recurs after an instruction exists, deciding a violation needs judgment, **and** the decision can be written as a repeatable procedure. Write the actual verify skill, `verify-<category>`, from the template in `${CLAUDE_SKILL_DIR}/references/verify-skill.md`.
- `hook`: it recurs after an instruction (or a check) exists **and** a script can check it mechanically. Write the actual hook config and script (see `${CLAUDE_SKILL_DIR}/references/hooks.md`).
- `test`: the mistake is about the code's behaviour, not process. Write the actual test in the project's framework.

Scope:
- `project`: only makes sense in this repo (its layout, tools, conventions).
- `user`: the human's preferences or environment across repos (`~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills`, memory).
- `framework`: would help anyone using these plugins (a missing review specialist check, a better lead prompt, a change to the default selection table, a new catalog category with its description, usual stage and cheapest rule).

**Selection table.** From `specialists`, also consider (ranked with the rest, counting toward the five):
- *Drop* a specialist from a tag when it ran for that tag in at least `retro.drop_after_runs` runs and found nothing there; heavy ones first, since they cost the most. A tag's `floor` cannot be dropped; high `overlap` with another specialist is a reason to prefer the drop.
- *Add* a specialist to a tag when a category escaped (`by_tag.<tag>.escaped`) in at least `retro.add_after_escapes` runs with that tag and the specialist that owns the category (its `categories` in the table) was not chosen; or *enable* an opt-in one that owns it.
- A specialist with low `precision` (most of its findings rejected) or a high `miss_rate` needs its brief rewritten, not a table change: a framework proposal.
- Override `errors` are reported as found, not proposed around.
The change goes in the project's `.claude/agent-loop/selection.yml` (create it as `schema: 1` if missing; its shape is DESIGN.md's "Specialists"), with a ledger entry `rung: selection`, the `category` it targets, the `specialist` it adds or drops (`change: drop` for a drop), and `location: ".claude/agent-loop/selection.yml"`. A change the plugin's default table needs in every project is framework scope.

Each new rule gets a ledger entry: `id` (`<category>-<n>`), `category`, `rung`, `scope`, `location` (for a `check`, the skill's `SKILL.md` path; for a `selection`, the override file), `specialist` (a `selection` rule only), `summary`, `added` (today), `baseline` (occurrences of the category in this window before the rule), `history: []`.

### 5. Human gate

**Project scope.** Never touch the user's checkout or the default branch. Find the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, else `main` / `master`), then work in a temporary worktree:

```bash
BR=retro/$(date +%F)            # add -2, -3 ... if it exists
WT=$(mktemp -d /tmp/retro-wt-XXXXXX)
git worktree add -b "$BR" "$WT" <default-branch>
```

In `$WT`: first one commit `retro: verify ledger rules` with the history entries (and any retirements: remove the rule's text and its ledger entry together). Then **one commit per new or escalated rule**, each containing the rule (instruction text, verify skill, hook config + script, test, or selection override) **and** its ledger entry in `.claude/rules-ledger.yml` (create it as `schema: 1` / `rules:` if missing); an escalation also sets the lower rule's `superseded_by` to the new rule's id, in the same commit. Commit messages: `retro: <category> -> <rung>` with a two-line paraphrased rationale (counts, not quotes). Run the project's tests if a test or hook was added; follow a new verify skill's procedure once, read-only, as its reference says. Then `git worktree remove "$WT"`; the branch stays. Do not push. Each write and git command here asks the human for permission; that is intended.

**User scope.** Show each change as a unified diff against the current file, or against nothing for a new one such as `~/.claude/skills/verify-<category>/SKILL.md` (including the `~/.claude/rules-ledger.yml` entry), and ask. Apply only the ones the human approves, exactly as shown.

**Framework scope.** Append to `<repo>/.claude/runs/framework-proposals.md` (create it if missing): a dated heading, the category, count and severity, the proposed change to the plugin, and paraphrased evidence only (no `excerpt` text, quoted or not). Never file it anywhere.

### 6. Report

Finish with:

1. **Rules verified**: table of id, category, occurrences since added, verdict, action.
2. **Specialists**: table of specialist, runs, precision, misses (and miss rate), and the tags where it caught nothing or missed something; then each tag's escaped categories.
3. **Proposals**: table of category, count, severity, rung, scope, where (branch + commit, diff awaiting yes, or framework-proposals.md).
4. **Not proposed**: one-off notes, false positives discarded, candidates cut by the five-proposal limit, and why.
5. How to review: `git log -p <default>..retro/YYYY-MM-DD`, then merge or delete the branch.

Delete the miner output at the end: `rm -f "<OUT>"` with the exact path `mktemp` printed. Never a glob: other retros may be running.

## Recording a session (`--record`)

Write `<repo>/.claude/runs/YYYY-MM-DD-<slug>.yml` for the current session in the run-record shape from `${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md` (`schema: 1`, `date`, `task`, `repo`, `outcome`, `rounds`, `stages`, `findings`, optional `plan`, `plan_approved`, `baseline_failures`, `rejected`, `notes`). Findings are only things that went wrong and were caught (by a stage, a hook, CI or the human), each with a reused category (from `${CLAUDE_PLUGIN_ROOT}/docs/categories.md`, the ledgers or earlier records) where one fits. No secrets, private hostnames, personal data or quotes from the conversation; paraphrase. Show the file to the human after writing it. If `.claude/runs/` is not gitignored and the project has not decided, mention that committing or ignoring `.claude/runs/` is the project's choice.
