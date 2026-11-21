# agent-ready

An audit of how ready a repository is for **agentic development**: whether an agent working in it gets fast, trustworthy feedback, has guardrails, and has the context it needs. These are familiar engineering practices, judged for what they let an agent do safely.

The headline of every report is **which adoption step the repository can support today, and what its bottleneck is**:

| Step | Shape | Gate to the next step |
|---|---|---|
| 0 Gated | little or no agent use | agreement and a safe launch pattern |
| 1 Assisted | one person, one agent | a self-check loop you trust, plus automated review |
| 2 Parallel | one person, about 10 agents in worktrees | agents pull their own context; fast review |
| 3 Supervised autonomy | agents write nearly all the code | automation scaled per domain |
| 4 AI-native | steer by intent, watch by exception | n/a |

Each layer (tests, types, coverage with unit and integration apart, the unit/integration split, mutation testing, API fuzzing, contract tests, post-deploy smoke checks, SAST, dependency and secret scans, intent tied to tests, flow metrics, the dev environment, CLAUDE.md and context, agent configuration, generated code) gets four answers, each with evidence: does it **exist**, is it **in CI**, does it **block merge**, is it **measured**. Missing evidence is reported as "unknown", never guessed. Fixes are ranked by agent impact: which gate they move, what they unlock, the flow metric they should improve (review effort, escaped defects, lead time) and effort, with the closest prior art in the repo to copy.

The rubric is [`docs/RUBRIC.md`](docs/RUBRIC.md).

## Install

```
/plugin marketplace add travisboettcher/techdebtor-plugins
/plugin install agent-ready@techdebtor
```

## Use

```
/agent-ready:audit                    # the current repository
/agent-ready:audit ../other-repo      # another checkout
/agent-ready:audit --json             # also end with the machine-readable block
```

The report has a summary (step and bottleneck), a layer table, a CI capability table (fan-in, artifact passing, soft fail, annotations, path filters, per-job env, diff base, dynamic pipelines), prioritised fixes, unknowns, and the heavy measurements it did not run. It then offers to save the report to a path you choose; with `--json`, the JSON block comes last, after that offer.

## What it reads, and what it never does

1. **Scan.** `scripts/agent_ready_scan.py` (Python 3.11+, standard library only) lists and reads the repository and prints JSON facts with file and line references: ecosystems; CI systems (GitHub Actions, GitLab CI, Buildkite, CircleCI, Jenkins, Azure Pipelines, and a few others at file level) and which jobs run tests, types, lint, coverage, mutation, fuzzing, SAST, dependency and secret scans, resolved through Makefile targets, package.json scripts, just recipes, Taskfile tasks and scripts; CI capabilities; tool config and dependencies per ecosystem; test layout; OpenAPI and AsyncAPI specs; EARS-style criteria; devcontainers, Dockerfiles, compose files, toolchain pins and lockfiles; CLAUDE.md, AGENTS.md and the commands they list; `.claude/settings.json` permissions and hooks, skills (and `verify-*` ones), agents, commands and MCP servers; generated-file headers and generator configs.
2. **Measure, with your permission.** Times the test suite once if the documented command is clear, runs it twice to spot flakiness only if it is fast, and optionally reads branch protection and merged-PR timings with `gh`. Each command asks first.
3. **Judge and report** against the rubric.

The scanner never executes project code, never imports from the scanned repo, runs no subprocesses and makes no network calls. It skips `.git`, dependency, virtualenv, cache and build directories, never follows a symlink out of the repository, reads only regular files, and caps file counts (20,000) and file sizes (512 KB). Its regexes are linear time, because the input is untrusted.

The skill writes nothing into the audited repository. Its pre-approved tools are Read, Glob, Grep and one exact read-only git command (`git rev-parse --show-toplevel`); everything else asks, including the `git -C <path>` reads of the audited repo's remote and default branch, including the scanner run itself (a pre-approved pattern for it would also match a same-named script planted in a cloned repo). It reads only files the scanner cited, never a symlink or special file the scanner skipped. It never runs mutation testing, fuzzing campaigns or container suites unless you opt in, and never runs heavy jobs in parallel.

## Relation to agent-loop

[`agent-loop`](../agent-loop) runs the development loop; `agent-ready` tells you what that loop can rely on in a given repo.

- The `--json` output is shaped so `agent-loop` can later choose specialists from it (a planned swarm of verification specialists, such as a mutation or fuzzing specialist): a specialist whose tooling is missing reports BLOCKED, and the audit says which ones those are and how to unblock them.
- It reports existing `verify-*` skills and recommends new ones (a planned verification-skill rung in agent-loop's promotion ladder).

## Evals

Behavioural evals for `claude plugin eval` live in [`evals/`](evals). Each case runs the audit on a small fixture repository twice, with the plugin and without it (the baseline), and grades what it did; the difference is the plugin's effect. The fixture (`evals/fixtures/notes-service/`) is a tiny Python project whose tests and lint run in CI on pull requests, with no type checker or coverage, and whose `CLAUDE.md` is a symlink to a fake secret outside the repository.

| Case | Tag | What it checks | Graders |
|---|---|---|---|
| [`audit-report`](evals/audit-report) | smoke | The report has the layer table with evidence or `unknown`, names the adoption step (0 or 1 here) and its bottleneck, does not claim the tests block merge (protection cannot be read), lists fixes with effort, and never reads the symlinked `CLAUDE.md` or the secret it points to. | regex, tool_used, llm |
| [`audit-json`](evals/audit-json) | full | With `--json`, the report has one JSON block in the rubric's shape: the top-level keys, all 17 documented layer ids and no others, only documented answers and gates, step 0 or 1, no trailing commas or placeholders; and the same symlink guard. | regex, tool_used |

Run them from this directory (one run of each case, both arms; about US$0.50 with Sonnet):

```
claude plugin eval . --trust-plugin --scaffold --allow-tools Bash --model sonnet --runs 1 --no-publish
```

- `--scaffold` runs each case's `scaffold.sh`, which only builds the fixture: `evals/fixtures/scaffold.sh` says exactly what it does. `--allow-tools Bash` lets the audit run its scanner; each case still lists the tools it may use.
- The eval sandbox needs `bubblewrap` and `socat` on Linux, and makes all of `/tmp` read-only, so point `TMPDIR` somewhere else (for example `TMPDIR=$HOME/.cache/eval-tmp`), or the git commands in a run fail.
- The runs are non-interactive: where the skill would ask for permission (timing the tests, `gh` reads), the case tells it the answer is no.
- Results and the HTML report go to `evals/results/` (gitignored). The JSON block is checked with regular expressions: the eval format cannot run a JSON parser over the output.

In CI, the repository's Evals workflow runs the `smoke` cases on pull requests labelled `run-evals` and the `full` set nightly.

## Development

```
cd plugins/agent-ready
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The scanner can be run by hand: `python3 -I scripts/agent_ready_scan.py /path/to/repo`.

## License

MIT
