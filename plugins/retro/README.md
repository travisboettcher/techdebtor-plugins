# retro

The self-improvement loop for Claude Code. `/retro` mines recent run records and session transcripts for the places where something went wrong (you corrected the agent, interrupted it, denied a tool call, or a later stage caught a mistake), finds the categories that keep recurring, and proposes the cheapest rule that would stop each one. On the next retro it checks whether those rules worked.

The model does not learn; the scaffolding around it does. A rule only counts as an improvement once a later retro shows its category stopped recurring.

## The loop

```
lead runs ──► run records ──┐
ordinary sessions ──► transcripts ──┤
                                    ▼
                                 /retro ──► proposals (branch / diff) ──► you merge
                                    │
                         rules ledger ◄── each merged rule, with the category it targets
                                    │
                    next /retro: did the category stop recurring? keep / escalate / retire
```

1. **Mine.** `scripts/retro_mine.py` (Python 3.11+, standard library only) reads `.claude/runs/*.yml`, both rules ledgers, and this project's transcripts under `~/.claude/projects/` (including its worktrees). It emits redacted JSON: correction, interrupt, denial and revert signals, category counts, and each ledger rule's occurrences since it was added.
2. **Verify.** Every ledger rule gets a verdict: `working` (its category has not recurred), `recurring` (it has: escalate or rewrite), or `dormant` (nothing for 90 days: retire it).
3. **Cluster** signals and findings into categories, reusing existing ones, and count recurrences. One-offs that are not critical stay notes.
4. **Propose** at most about five changes, highest recurrence x severity first, preferring to delete or merge rules over adding them.
5. **Gate.** Nothing lands without you (see below).

## The promotion ladder

| Rung | When |
|---|---|
| `note` | Seen once: it stays in the run record; no rule yet. |
| `instruction` | Seen twice, or once at `critical` severity: a line in CLAUDE.md, a skill, or memory. |
| `hook` | Recurs after an instruction exists, and can be checked mechanically: a hook or CI check that blocks it. |
| `test` | The mistake is about the code's behaviour, not process: a test or eval that fails on it. |

## Human gate and scope

- **Project** rules (this repo's layout, tools, conventions) go on a new local branch `retro/YYYY-MM-DD`, created in a temporary worktree so your checkout is untouched: one commit per rule, each including its ledger entry. Never on the default branch, never pushed. Review with `git log -p main..retro/YYYY-MM-DD`, then merge or delete it.
- **User** rules (your preferences across repos) are shown as a diff to `~/.claude/...` and applied only after you say yes.
- **Framework** ideas (improvements to these plugins) are appended to `.claude/runs/framework-proposals.md` as a draft for you to take upstream. Nothing is filed automatically.

## Where state lives

Nothing project-specific lives in the plugin.

| What | Project | User |
|---|---|---|
| Run records | `<repo>/.claude/runs/YYYY-MM-DD-<slug>.yml` | - |
| Rules ledger | `<repo>/.claude/rules-ledger.yml` (committed) | `~/.claude/rules-ledger.yml` |
| Rules | `CLAUDE.md`, `.claude/skills`, `.claude/settings.json` hooks, tests | `~/.claude/CLAUDE.md`, `~/.claude/skills`, `~/.claude/settings.json`, memory |
| Framework proposals | `<repo>/.claude/runs/framework-proposals.md` | same |

Whether `.claude/runs/` is committed or gitignored is up to each project.

## Privacy

Transcripts contain secrets and private details, so the miner treats them as hostile input:

- Everything that leaves it is redacted first: API keys and tokens (GitHub, OpenAI/Anthropic-style `sk-`, Slack, AWS), JWTs, long hex and base64 runs, `Authorization` / `Bearer` headers, credentials in URLs, `SOMETHING_KEY|TOKEN|SECRET|PASSWORD=value`, private key blocks, emails, IPv4 addresses, and the user name in home-directory paths. When in doubt it redacts.
- Excerpts are short (300 characters for your message, 200 for the agent action before it).
- The skill never reads transcripts directly and never copies raw transcript text into a proposal, commit, ledger or record: evidence is paraphrased or taken from the miner's redacted output.
- Nothing is sent anywhere. The plugin makes no network calls.

## Install

```
/plugin marketplace add travisboettcher/agent-loops
/plugin install retro@agent-loops
```

## Use

```
/retro               # last 30 days
/retro 14d           # another window (14d, 2w, 12h, or an ISO date)
/retro --record      # write a run record for the current session
```

Run it weekly, or after a burst of work. A retro over a quiet week is cheap and still re-verifies the ledger.

## With and without `lead`

`retro` works on its own: transcripts alone give it corrections, interrupts, denials and reverted edits. It is better with the `lead` plugin (or hand-written `/retro --record` records), because run records carry categorised findings from each stage, and ledger verification counts those categories exactly.

## Development

```
cd plugins/retro
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The miner can also be run by hand: `python3 scripts/retro_mine.py --root . --since 14d`.

## License

MIT
