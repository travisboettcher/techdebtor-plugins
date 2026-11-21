# agent-loop

An agent graph for development that improves itself.

- **`/agent-loop:lead <task>`** is a tech lead: it preflights the repo, plans the task as small units with testable criteria, runs test-writer, implementer, tester and independent reviewer agents in a bounded loop, gates the result against a baseline, and writes a run record of every mistake any stage caught.
- **`/agent-loop:retro`** closes the loop: it mines those run records and your session transcripts for what keeps going wrong, proposes the cheapest rule that would stop each recurring mistake, and on the next retro checks whether each rule worked.

The model does not learn; the scaffolding around it does. A rule only counts as an improvement once a later retro shows its category stopped recurring. The contract between the two halves (formats, ladder, verdicts, scope, privacy) is [`docs/DESIGN.md`](docs/DESIGN.md).

## Install

```
/plugin marketplace add travisboettcher/techdebtor-plugins
/plugin install agent-loop@techdebtor
```

## Use

```
/agent-loop:lead add a --dry-run flag to the export command
/agent-loop:retro               # last 30 days
/agent-loop:retro 14d           # another window (14d, 2w, 12h, or an ISO date)
/agent-loop:retro --record      # write a run record for the current session
```

`lead` is user-invoked only (it launches several agents); give a round limit in the task if 3 is wrong, and a branch budget if about 300 changed lines per unit is wrong. The agents (`agent-loop:test-writer`, `agent-loop:implementer`, `agent-loop:tester`, `agent-loop:reviewer`) can be used directly, but expect a brief with acceptance criteria and rules. Run `retro` weekly, or after a burst of work; a retro over a quiet week is cheap and still re-verifies the ledger.

## How it works

### `/agent-loop:lead`: the graph

1. **Understand.** Reads `CLAUDE.md` and, if present, `.claude/rules-ledger.yml` and `~/.claude/rules-ledger.yml`. Every applicable rule goes into a rules brief that every agent receives. Acceptance criteria must be testable (EARS form recommended), each naming its test or verifier; with none, it stops and asks.
2. **Preflight.** A clean tree; when starting on the default branch, a work branch from an up-to-date `origin/<default>`; the build, lint and test commands; a baseline test run, so tests that already fail are never blamed on the change; and the project's generators and stale-artifact checks, with every new file checked against their globs.
3. **Plan.** The approach and the main alternative rejected, small ordered units within a branch budget (about 300 changed lines each by default, split by behaviour with tests alongside), a test plan from the criteria, risks and what is out of scope. Large or risky tasks wait for your approval, and nothing is implemented or committed before it.
4. **Build each unit.** The `test-writer` agent writes failing tests from the criteria and interfaces, never the implementation; the `implementer` makes them pass; the lead reruns the tests itself rather than trusting the report. One commit per unit, if you asked for commits. Heavy jobs (full builds, mutation testing) never run in parallel.
5. **Test.** The `tester` agent runs the project's real verifiers (including the project's and your `verify-*` skills that the plan chose for the changed files) and reports pass/fail with output, separating pre-existing failures. When the change touches tests or measurement, it also checks measurement invariants (a subset run never beats the full run, order independence, no silent allowlists, and more). It does not fix code.
6. **Review.** The `reviewer` agent gets the whole diff, the acceptance criteria and the rules brief, and nothing else: no implementer reasoning, no lead conclusions. It reports only findings it has verified, each with category, severity, file:line and a failure scenario, or "no findings".
7. **Loop.** Fix, test, review until clean, or 3 rounds, then stop and report.
8. **Pre-push gate.** The final diff must be the one last reviewed; then whatever your `CLAUDE.md` requires before a push, plus the generated-artifact checks, reported against the baseline.
9. **Record.** Writes `.claude/runs/YYYY-MM-DD-<slug>.yml`, including the plan record, when the plan was approved, and the baseline failures, then checks it with `scripts/record_gate.py`: the run is not done unless the change still matches the fingerprint taken for the last review and no commit of the run predates a required plan approval (yours; in a delegated run, relayed by the delegator).

It never merges and never pushes to the default branch. It commits only if you asked for commits, a branch or a pull request in the session, and pushes or opens a draft pull request only if you asked for that; otherwise it leaves the change uncommitted with the units listed.

### `/agent-loop:retro`: the feedback loop

```
/agent-loop:lead runs ──► run records ──┐
             ordinary sessions ──► transcripts ──┤
                                                 ▼
                                       /agent-loop:retro ──► proposals (branch / diff) ──► you merge
                                                 │
                                      rules ledger ◄── each merged rule, with the category it targets
                                                 │
                        next /agent-loop:retro: did the category stop recurring? keep / escalate / retire
```

1. **Mine.** `scripts/retro_mine.py` (Python 3.11+, standard library only) reads `.claude/runs/*.yml` from every worktree, both rules ledgers, and this project's transcripts under `~/.claude/projects/` (including its worktrees). It emits redacted JSON: correction, interrupt, denial and revert signals, category counts, and each ledger rule's occurrences since it was added.
2. **Verify.** Every ledger rule gets a verdict: `working` (nothing in its category got past it; a hook or check catching the mistake shows it fires), `recurring` (something got past it: escalate or rewrite), or `dormant` (nothing for 90 days: retire it).
3. **Cluster** signals and findings into categories, reusing existing ones, and count recurrences. One-offs that are not critical stay notes.
4. **Propose** at most about five changes, highest recurrence x severity first, preferring to delete or merge rules over adding them.
5. **Gate.** Nothing lands without you (see below).

`retro` works without `lead`: transcripts alone give it corrections, interrupts, denials and reverted edits. It is better with run records, because they carry categorised findings from each stage and ledger verification counts those exactly.

## Run records

Every run, including abandoned ones, ends with a YAML record in `.claude/runs/` in the format defined in [`docs/DESIGN.md`](docs/DESIGN.md):

```yaml
schema: 1
date: 2026-11-21
task: "Add a --dry-run flag to the export command"
repo: my-project
outcome: completed
rounds: 2
stages: [plan, implement, test, review, implement, test, review]
plan_approved: n/a            # approval was not required for this task
findings:
  - stage: implement          # where the mistake was made; caught_by says who noticed
    category: doc-drift
    severity: minor
    detail: "The --help text still described the old default."
    caught_by: reviewer
    fixed: true
notes: ""
```

A finding is something that went wrong and was caught, by any stage, by you, or by the lead itself. Categories start from the catalog in [`docs/categories.md`](docs/categories.md) (each with its usual stage and the cheapest known rule) and are reused from earlier records and the rules ledger so they can be counted across runs; a retro can propose new ones for the catalog. Records hold no secrets or personal data.

On first use the lead suggests adding `.claude/runs/` to `.gitignore`; it does not change it without asking. Commit the records instead if you want them shared.

## The promotion ladder

| Rung | When |
|---|---|
| `note` | Seen once: it stays in the run record; no rule yet. |
| `instruction` | Seen twice, or once at `critical` severity: a line in CLAUDE.md, a skill, or memory. |
| `check` | Recurs after an instruction exists, needs judgment to verify, and can be written as a repeatable procedure: a `verify-<category>` skill that reports violations as `path:line` lines and PASS/FAIL. |
| `hook` | Recurs after an instruction (or a check) exists, and can be checked mechanically: a hook or CI check that blocks it. |

A `check` is a read-only skill in `.claude/skills/` or `~/.claude/skills/`. The lead picks the ones that apply to each unit's files and the tester follows them like any verifier; it never runs a fix step. A check that mistakes keep getting past moves to a hook or test where it can be made mechanical, otherwise its procedure is rewritten. The shape is in [`docs/DESIGN.md`](docs/DESIGN.md) ("Verify skills"), with a worked example in [`docs/examples/verify-doc-drift/SKILL.md`](docs/examples/verify-doc-drift/SKILL.md).
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

- Everything that leaves it is redacted first: API keys and tokens (GitHub, GitLab, npm, PyPI, Hugging Face, OpenAI/Anthropic-style `sk-`, Slack, AWS), JWTs, long hex and base64 runs, `Authorization` / `Bearer` headers, credentials in URLs and on command lines (`curl -u user:pass`, `--password VALUE`, `mysql -pVALUE`), `SOMETHING_KEY|TOKEN|SECRET|PASSWORD=value`, private key blocks, emails, IPv4 addresses, and the user name in home-directory paths, including when glued to an identifier (`host_10.0.0.5`). When in doubt it redacts.
- Excerpts are short (300 characters for your message, 200 for the agent action before it).
- The skill never reads transcripts directly and never copies raw transcript text into a proposal, commit, ledger or record: evidence is paraphrased or taken from the miner's redacted output.
- Nothing is sent anywhere. The plugin makes no network calls.

## Development

```
cd plugins/agent-loop
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The miner can also be run by hand: `python3 scripts/retro_mine.py --root . --since 14d`.

## License

MIT
