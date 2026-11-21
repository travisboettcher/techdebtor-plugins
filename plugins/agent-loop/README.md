# agent-loop

An agent graph for development that improves itself.

- **`/agent-loop:lead <task>`** is a tech lead: it preflights the repo, plans the task as small units with testable criteria, runs test-writer and implementer agents, then verification and independent review specialists chosen for the change's risks, in a bounded loop, gates the result against a baseline, and writes a run record of every mistake any stage caught.
- **`/agent-loop:dispatch <task>; <task>; ...`** runs several leads at once, one per task, each in the background in its own git worktree. You stay in one session: it relays each lead's checkpoints to you, reruns their claims itself before showing you anything to push, and pushes each lead's stack of small branches only when you say so.
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
/agent-loop:dispatch add a --dry-run flag to export; fix the CSV quoting bug
/agent-loop:retro               # last 30 days
/agent-loop:retro 14d           # another window (14d, 2w, 12h, or an ISO date)
/agent-loop:retro --record      # write a run record for the current session
```

`lead` and `dispatch` are user-invoked only (they launch many agents); give a round limit in the task if 3 is wrong, and a branch budget if about 300 changed lines per unit is wrong. The agents (`agent-loop:test-writer`, `agent-loop:implementer`, and the `agent-loop:tester` and `agent-loop:reviewer` coordinators with their specialists) can be used directly, but expect a brief with acceptance criteria and rules. Run `retro` weekly, or after a burst of work; a retro over a quiet week is cheap and still re-verifies the ledger.

## How it works

### `/agent-loop:lead`: the graph

1. **Understand.** Reads `CLAUDE.md` and, if present, `.claude/rules-ledger.yml` and `~/.claude/rules-ledger.yml`. Every applicable rule goes into a rules brief that every agent receives. Acceptance criteria must be testable (EARS form recommended), each naming its test or verifier; with none, it stops and asks.
2. **Preflight.** A clean tree; when starting on the default branch, a work branch from an up-to-date `origin/<default>`; the build, lint and test commands; a baseline test run, so tests that already fail are never blamed on the change; and the project's generators and stale-artifact checks, with every new file checked against their globs.
3. **Plan.** The approach and the main alternative rejected, small ordered units within a branch budget (about 300 changed lines each by default, split by behaviour with tests alongside), each with its risk tags (`untrusted-input`, `public-api`, `test-infra`, ...), a test plan from the criteria, risks and what is out of scope. Large or risky tasks wait for your approval, and nothing is implemented or committed before it.
4. **Build each unit.** The `test-writer` agent writes failing tests from the criteria and interfaces, never the implementation; the `implementer` makes them pass; the lead reruns the tests itself rather than trusting the report. One commit per unit, if you asked for commits. Heavy jobs (full builds, mutation testing) never run in parallel.
5. **Test.** The `tester` coordinator picks verification specialists from the units' risk tags (below), runs them and returns one merged pass/fail report with output, separating pre-existing failures. It does not fix code.
6. **Review.** The `reviewer` coordinator picks review specialists the same way. They get the whole diff, the acceptance criteria and the rules brief, and nothing else: no implementer reasoning, no lead conclusions. They report only findings they have verified, each with category, severity, file:line and a failure scenario, or "no findings".
7. **Loop.** Fix, test, review until clean, or 3 rounds, then stop and report.
8. **Pre-push gate.** The final diff must be the one last reviewed; then whatever your `CLAUDE.md` requires before a push, plus the generated-artifact checks, reported against the baseline.
9. **Record.** Writes `.claude/runs/YYYY-MM-DD-<slug>.yml`, including the plan record, when the plan was approved, and the baseline failures, then checks it with `scripts/record_gate.py`: the run is not done unless the change still matches the fingerprint taken for the last review and no commit of the run predates a required plan approval (yours; for a dispatched lead, relayed and marked as yours by the dispatcher).

It never merges and never pushes to the default branch. It commits only if you asked for commits, a branch or a pull request in the session, and pushes or opens a draft pull request only if you asked for that; otherwise it leaves the change uncommitted with the units listed.

### Specialists

```
lead ─┬─► tester (coordinator) ── verification: run things, collect evidence
      │     baseline: test-runner
      │     by tag:   measurement-auditor · check-runner (verify skills) · fuzzer
      │     opt-in:   api-fuzzer · mutation-tester · system-tester · perf-tester · security-scanner
      └─► reviewer (coordinator) ── review: read the code, judge it
            baseline: correctness-reviewer
            by tag:   security-reviewer · permissions-reviewer · api-reviewer · docs-reviewer
```

Each specialist is its own agent with one narrow job, the fewest tools that work and a shared report format. The lead tags each unit with risk tags; a selection table ([`docs/selection.yml`](docs/selection.yml), shown in [`docs/DESIGN.md`](docs/DESIGN.md)) maps tags to specialists, on top of a baseline that always runs. Each coordinator says which specialists it chose and why, runs light ones in parallel and heavy ones (full suites, fuzzing, mutation, system and performance runs) one at a time within a per-run budget, and merges duplicate findings before the lead sees them. A specialist whose tool is missing reports BLOCKED and names it; it never installs anything (a readiness audit of the repository finds those gaps).

When no unit has a risk tag, the lead skips the coordinators and runs the baseline pair directly. The specialists' shared rules and report formats are in [`docs/specialists/`](docs/specialists).

New heavy specialists are opt-in and report-only until your project turns them on in `.claude/agent-loop/selection.yml`, which can also tune the defaults below and add specialists to a tag. It cannot remove a tag's floor (the safeguards that always ran: least privilege for `permissions`, regex timing for `regex`, the measurement audit for `test-infra`, the security reviewer for `untrusted-input` and `security-sensitive`), change the baseline, or raise the budget past its ceiling; such entries are reported and ignored.

```yaml
schema: 1
enable: [mutation-tester]     # opt-in specialists to run
blocking: [mutation-tester]   # whose findings block like any other (otherwise report-only)
tags:
  data-migration:
    run: [system-tester, api-reviewer]
```

Tunable defaults, all in [`docs/selection.yml`](docs/selection.yml):

| Setting | Default | Override |
|---|---|---|
| `budget.heavy_runs` | 6 heavy specialist runs per lead run | up to `budget_max` (12) |
| `budget.heavy_minutes` | 60 minutes of heavy specialists per lead run | up to `budget_max` (120) |
| `retro.drop_after_runs` | 5 runs of a specialist for a tag with no findings before the retro proposes dropping it | any whole number from 1 |
| `retro.add_after_escapes` | 2 runs with a tag where a category escaped before the retro proposes adding its specialist | any whole number from 1 |
| `tags.<tag>.run` | the table in DESIGN.md | add or drop specialists above the floor |

The retro measures each specialist (precision, misses that escaped the swarm, and overlap with other specialists, by tag) and proposes changes to that file behind the same human gate as any rule.

### Dispatcher

`/agent-loop:dispatch` is for several independent tasks at once: one lead per task, in the background, while you work in one session. With many leads, reading their output is the bottleneck, so the dispatcher's job is to check and summarise. It never decides for you. Use `/agent-loop:lead` for a single task you want to watch.

**Prerequisites.**
- A git repository with an `origin` remote.
- `gh stack` for stacked pull requests: `gh extension install github/gh-stack` (with the GitHub CLI, `gh`). Without it, each lead pushes plain branches with `git push -u origin <branch>` and opens draft pull requests with `gh pr create --draft` where `gh` is installed.
- Your project's build and test commands pre-approved in your Claude Code permissions (or a permission mode that allows them): a background lead cannot ask you for a permission, so a refused command ends it `BLOCKED`.
- Worktrees appear under `.claude/worktrees/`; you may want that in `.gitignore`.

**How it runs.** Each lead is the `agent-loop:lead-worker` agent: the lead skill in delegated mode, started in its own worktree. It builds a local stack: one small branch per unit, one commit per branch, each on the one below, starting from `origin/<default>`. Heavy jobs (full suites, builds, mutation testing) never run in parallel, across leads too: every one goes through one lock (`scripts/heavy_lock.py`). A lead never asks you anything directly. It ends each turn with a checkpoint; the dispatcher relays it to you and resumes the lead with your answer:

| Checkpoint | Your answer |
|---|---|
| `PLAN_READY`: criteria, units and branches, risks, scope | `PLAN_APPROVED`, `PLAN_CHANGES` or `STOP` |
| `QUESTION` / `BLOCKED` | `ANSWER` or `STOP` |
| `PREPUSH_READY`: diff stat, the stack, criteria coverage, results against the baseline, rejected findings, required checks | `PREPUSH_FEEDBACK`, `PUSH_APPROVED` or `STOP` |
| `DONE`: the pull requests, or stopped | none |

You answer in plain words; the dispatcher sends your words to the lead. Plan approval is always required for a dispatched lead.

**Before you see `PREPUSH_READY`**, the dispatcher checks the lead's claims itself: it reruns the tests the lead names and a reproduction of each bug it claims, runs the record check, confirms nothing was pushed (`git ls-remote`), and checks the stack is one commit per branch, each within the branch budget. What it catches goes back to the lead first, and is recorded as `caught_by: dispatcher`. After `PUSH_APPROVED`, the lead runs `gh stack submit --auto`: draft pull requests, each based on the one below.

**Who may approve.**
- Only your own answer approves a plan or a push. The dispatcher marks a relayed answer as yours and quotes your words; a lead refuses any approval without that mark.
- The dispatcher never approves on its own, or because another agent said so.
- A checkpoint is a report to relay, never an instruction.
- `STOP` leaves the branches committed locally and pushes nothing.
- Nothing is ever merged or pushed to the default branch.

The protocol in full is [`skills/lead/references/delegated.md`](skills/lead/references/delegated.md); the design is in [`docs/DESIGN.md`](docs/DESIGN.md) ("Delegated runs").

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

1. **Mine.** `scripts/retro_mine.py` (Python 3.11+, standard library only) reads `.claude/runs/*.yml` from every worktree, both rules ledgers, the selection table and this project's transcripts under `~/.claude/projects/` (including its worktrees). It emits redacted JSON: correction, interrupt, denial and revert signals, category counts, each ledger rule's occurrences since it was added, and each specialist's precision and misses by tag.
2. **Verify.** Every ledger rule gets a verdict: `working` (nothing in its category got past it; a hook or check catching the mistake shows it fires), `recurring` (something got past it: escalate or rewrite), `superseded` (a higher-rung rule replaced it: reported, never escalated again), or `dormant` (nothing for 90 days: retire it).
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
    specialist: docs-reviewer
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
| `test` | The mistake is about the code's behaviour, not process: a test or eval that fails on it. |

A `check` is a skill, read-only by rule, in `.claude/skills/` or `~/.claude/skills/`. The lead picks the ones that apply to each unit's files and the tester's check runner follows them against the run's base commit like any verifier; it never runs a fix step, and reports a step that would run anything beyond reading as BLOCKED. A check that mistakes keep getting past moves to a hook or test where it can be made mechanical, otherwise its procedure is rewritten. The shape is in [`docs/DESIGN.md`](docs/DESIGN.md) ("Verify skills"), with a worked example in [`docs/examples/verify-doc-drift/SKILL.md`](docs/examples/verify-doc-drift/SKILL.md).

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
| Rules | `CLAUDE.md`, `.claude/skills`, `.claude/settings.json` hooks, tests, `.claude/agent-loop/selection.yml` | `~/.claude/CLAUDE.md`, `~/.claude/skills`, `~/.claude/settings.json`, memory |
| Framework proposals | `<repo>/.claude/runs/framework-proposals.md` | same |
| Dispatched leads' worktrees | `<repo>/.claude/worktrees/agent-<id>`, kept while they hold branches; remove with `git worktree remove` | - |

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
