# Design

The `agent-loop` plugin has two halves, the `lead` skill (with its implementer, tester and reviewer agents) and the `retro` skill (with `scripts/retro_mine.py`). They share two file formats. This document is the contract between them and ships with the plugin (`${CLAUDE_PLUGIN_ROOT}/docs/DESIGN.md`); change it before changing either half.

## The loop

```
/agent-loop:lead run ──► run record ──┐
         ordinary sessions ──► transcripts ──┤
                                             ▼
                                   /agent-loop:retro ──► proposals (branch / draft) ──► human merges
                                             │
                                  rules ledger ◄── each merged rule, with the category it targets
                                             │
                    next /agent-loop:retro: did the category stop recurring? keep / escalate / retire
```

The model does not learn; the scaffolding around it does. A rule is only an improvement if a later retro can show its category stopped recurring.

## Where state lives

Nothing project-specific ever lives in the plugin.

| What | Project scope | User scope |
|---|---|---|
| Run records | `<repo>/.claude/runs/YYYY-MM-DD-<slug>.yml` | - |
| Rules ledger | `<repo>/.claude/rules-ledger.yml` (committed) | `~/.claude/rules-ledger.yml` |
| Rules themselves | `<repo>/CLAUDE.md`, `<repo>/.claude/skills`, `<repo>/.claude/settings.json` hooks, tests | `~/.claude/CLAUDE.md`, `~/.claude/skills`, `~/.claude/settings.json`, memory |
| Framework proposals | `<repo>/.claude/runs/framework-proposals.md` (a draft for the human to take upstream; never filed automatically) | same |

Run records are local evidence; projects decide whether to commit or gitignore `.claude/runs/` (the default `lead` setup suggests gitignoring it).

## Run record (`.claude/runs/*.yml`)

Written by the `lead` skill (`/agent-loop:lead`) at the end of every run, and by hand or by `/agent-loop:retro --record` for any session worth logging.

```yaml
schema: 1
date: 2026-11-21
task: "One-line description of the task"
repo: name-of-repo            # basename of the git root
outcome: completed            # completed | merged | reworked | abandoned | in-progress
rounds: 1                     # implement→test→review rounds run
stages:                       # what ran, in order; repeated stages repeat (implement, test, review, implement, ...)
  - plan
  - implement
  - test
  - review
findings:                     # anything a later stage (or the human) had to catch or fix
  - stage: implement          # where the mistake was made: plan | implement | test | review
    category: generated-file-hand-edit   # kebab-case; reuse existing categories (see ledger) before inventing one
    severity: major           # minor | major | critical
    detail: "Edited the generated compose file instead of its source."
    caught_by: reviewer       # which stage noticed: tester | reviewer | human | ci | hook | self
    fixed: true
rejected:                     # optional: findings a stage reported that turned out to be wrong
  - stage: review             # here: the stage that reported the wrong finding
    category: missing-null-check
    reason: "The value is validated by the caller at the cited line."
notes: "Free text, optional."
```

Rules:
- `category` is the unit of measurement. Prefer an existing category from the ledger or earlier records; a new one is fine when nothing fits.
- A finding is something that went wrong and was caught by a *later* stage, the human, CI or a hook, not a summary of the work. Mistakes an agent catches in its own work before reporting are not findings.
- `stage` is where the mistake was made, never who noticed it; `caught_by` is who noticed. A defect the tester or reviewer finds in the implementation is `stage: implement` with `caught_by: tester` or `caught_by: reviewer`. A missing or wrong acceptance criterion or verifier, a wrong plan or a bad brief (the lead's own mistakes) is `stage: plan`. `stage: test` and `stage: review` are only for mistakes the tester or reviewer made themselves (a check skipped, a failure misreported) that someone else caught later. `caught_by: self` means the stage that made the mistake noticed it later in the run.
- `outcome` is `completed` when the run finished and is waiting on the human, and `in-progress` only when it stopped part-way. The human's decision (`merged`, `reworked`, `abandoned`) replaces it when known.
- `rejected` records false positives, so a retro can measure how often a stage (usually the reviewer) is wrong; a stage that is often wrong is itself a candidate for a rule.
- Never put secrets, tokens, hostnames of private systems, or personal data in a record.

## Rules ledger (`rules-ledger.yml`)

Maintained by `/agent-loop:retro`. One entry per rule the human merged.

```yaml
schema: 1
rules:
  - id: generated-file-hand-edit-1
    category: generated-file-hand-edit
    rung: hook                 # note | instruction | hook | test
    scope: project             # project | user
    location: ".claude/settings.json (PreToolUse hook)"
    summary: "Block edits to files whose first line is '# Generated by'."
    added: 2026-11-21
    baseline: 3                # occurrences of the category in the window before the rule was added
    history:                   # appended by each retro that checks this rule
      - date: 2026-12-05
        occurrences_since: 0
        verdict: working       # working | recurring | dormant
```

## The promotion ladder

| Rung | When |
|---|---|
| `note` | Seen once: it stays in the run record; no rule yet. |
| `instruction` | Seen twice, or once at `critical` severity: a line in CLAUDE.md, a skill, or memory. |
| `hook` | Recurs after an `instruction` exists, and can be checked mechanically: a hook or CI check that blocks it. |
| `test` | The mistake is about behaviour of the code, not process: a test or eval that fails on it. |

Verification on each retro, for every ledger rule. Occurrences are counted strictly after `added` (a record dated the same day as the rule predates it), from run-record findings plus transcript signals the retro assigned to the category. The windows:
- Run records are small, so the miner reads all of them (from every worktree of the project) whatever `--since` says; a rule's run-record occurrences cover everything since its `added` date. Only `category_counts` is limited to the requested window.
- Transcript signals cover the requested window, extended back automatically to the `added` date of the oldest rule in either ledger, but never more than 90 days before the retro. A rule older than that is checked against the last 90 days of transcripts only. The miner reports the windows it actually used under `window`.

Verdicts:
- `working`: the category has not recurred since the rule was added.
- `recurring`: it has. Propose the next rung up (or a rewrite, if the rule is unclear).
- `dormant`: the rule is at least 90 days old and no work in that time touched what it governs, so there was nothing for it to prevent. The miner reports `days_since_added` and `records_since_added`; the retro judges relevance. Propose retiring it, so instructions don't accumulate forever.

Transcript signals arrive uncategorized; the retro assigns each a category (reusing existing ones) or discards it as a false positive before counting. A user ledger is checked against the run records of whichever project the retro runs in.

## Scope classification

Each proposal is classified before it is written:
- `project`: only makes sense in this repo (its file layout, tools, conventions).
- `user`: the human's preferences or environment, across repos.
- `framework`: would help anyone using these plugins (a better lead prompt, a missing reviewer check). Written to `framework-proposals.md` as a draft, with evidence paraphrased, never raw transcript text.

## Human gate

`/agent-loop:retro` never edits instructions, hooks or the ledger on the default branch. It writes proposals on a new branch (project scope) or as a reviewable diff (user scope) and stops. The ledger entry is added in the same change as the rule, so merging the rule is what records it. The retro skill pre-approves only reading (files and a few read-only git commands; not `git log`/`diff`/`show`, whose `--output=<file>` writes), so every file write, worktree, commit or push it attempts goes through Claude Code's permission prompt: that prompt is part of the gate. Running the miner asks too, once per retro: a pre-approval pattern for `*/scripts/retro_mine.py` would also pre-approve a script of that name planted in any cloned repo.

## Privacy

Transcripts contain secrets and private details. The miner redacts anything secret-shaped (tokens, keys, passwords, `KEY=value` assignments, command-line credentials, bearer headers, IP addresses, emails, and the local user name, also when glued to an identifier with `_`) before any text leaves it, and keeps excerpts short. Nothing from a transcript is ever sent anywhere by these plugins.
