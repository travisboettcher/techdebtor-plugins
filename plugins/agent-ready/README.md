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

The report has a summary (step and bottleneck), a layer table, a CI capability table (fan-in, artifact passing, soft fail, annotations, path filters, per-job env, diff base, dynamic pipelines), prioritised fixes, unknowns, and the heavy measurements it did not run. At the end it offers to save the report to a path you choose.

## What it reads, and what it never does

1. **Scan.** `scripts/agent_ready_scan.py` (Python 3.11+, standard library only) lists and reads the repository and prints JSON facts with file and line references: ecosystems; CI systems (GitHub Actions, GitLab CI, Buildkite, CircleCI, Jenkins, Azure Pipelines, and a few others at file level) and which jobs run tests, types, lint, coverage, mutation, fuzzing, SAST, dependency and secret scans, resolved through Makefile targets, package.json scripts, just recipes, Taskfile tasks and scripts; CI capabilities; tool config and dependencies per ecosystem; test layout; OpenAPI and AsyncAPI specs; EARS-style criteria; devcontainers, Dockerfiles, compose files, toolchain pins and lockfiles; CLAUDE.md, AGENTS.md and the commands they list; `.claude/settings.json` permissions and hooks, skills (and `verify-*` ones), agents, commands and MCP servers; generated-file headers and generator configs.
2. **Measure, with your permission.** Times the test suite once if the documented command is clear, runs it twice to spot flakiness only if it is fast, and optionally reads branch protection and merged-PR timings with `gh`. Each command asks first.
3. **Judge and report** against the rubric.

The scanner never executes project code, never imports from the scanned repo, runs no subprocesses and makes no network calls. It skips `.git`, dependency, virtualenv, cache and build directories, never follows a symlink out of the repository, reads only regular files, and caps file counts (20,000) and file sizes (512 KB). Its regexes are linear time, because the input is untrusted.

The skill writes nothing into the audited repository. Its pre-approved tools are Read, Glob, Grep and three exact read-only git commands; everything else asks, including the scanner run itself (a pre-approved pattern for it would also match a same-named script planted in a cloned repo). It never runs mutation testing, fuzzing campaigns or container suites unless you opt in, and never runs heavy jobs in parallel.

## Relation to agent-loop

[`agent-loop`](../agent-loop) runs the development loop; `agent-ready` tells you what that loop can rely on in a given repo.

- The `--json` output is shaped so `agent-loop` can later choose specialists from it (agent-loop issue #3, the specialist swarm): a specialist whose tooling is missing reports BLOCKED, and the audit says which ones those are and how to unblock them.
- It reports existing `verify-*` skills and recommends new ones (agent-loop issue #1, the verification-skill rung).

## Development

```
cd plugins/agent-ready
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The scanner can be run by hand: `python3 -I scripts/agent_ready_scan.py /path/to/repo`.

## License

MIT
