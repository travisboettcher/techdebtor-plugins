# Rubric

The contract for `/agent-ready:audit`. The skill follows it; `scripts/agent_ready_scan.py` collects the facts it judges. Change this file before changing either.

The audit answers one question first: **which adoption step can this repository support today, and what is its bottleneck?** Everything else (the layer table, the CI capability table, the fixes) is the evidence for that answer and the way past the bottleneck.

**Measure flow, not output.** A recommendation is worth making if it reduces review effort, escaped defects or lead time. Lines of code, number of agents and number of checks are not goals.

## Adoption steps

Teams move through about five steps of AI use. Each step clears one bottleneck and exposes the next. The steps build on each other: diagnose the real bottleneck before adding anything.

| Step | Shape | Bottleneck | Gate to the next step |
|---|---|---|---|
| 0 Gated | little or no agent use | approvals, security, governance | agreement and a safe launch pattern |
| 1 Assisted | one person, one agent | your attention: you review every change | a self-check loop you trust, plus automated review |
| 2 Parallel | one person, about 10 agents in worktrees | reading what comes out | agents pull their own context; fast review; agents start agents |
| 3 Supervised autonomy | agents write nearly all the code | trust in the loop | automation scaled per domain |
| 4 AI-native | steer by intent, watch by exception | finding work to automate | n/a |

The 2 → 3 gate is where teams stall: the question stops being "did you read the code?" and becomes "what context was missing?". Two traps to name when you see them: green checks that share the code's wrong assumptions (tests with no validity measure), and more agents before the loop has earned trust.

### Each gate as evidence

A repository **supports step N** when every gate below N is met with evidence. The **bottleneck** is the first unmet gate item (or items). The audit judges the repository, not the organisation: approvals and governance are reported as "not assessed".

| Gate | Met when the evidence shows | Layers |
|---|---|---|
| 0 → 1: one agent can work safely | An agent can set up, build and run the tests from documented commands; no secrets in the tree; agent permissions are configured or the defaults are acceptable. | dev environment, context, secret scan, agent configuration |
| 1 → 2: a self-check loop you trust, plus automated review | Tests, type checks and lint exist, run in CI on every pull request and block merge; the suite time is known and short enough to run per change; no flakiness seen; an automated review step exists (a review bot or AI review in CI, or a review agent or skill the team uses). | tests, types, coverage, agent configuration |
| 2 → 3: agents pull their own context; review is fast | Context is accurate and complete enough to act on (CLAUDE.md with commands, architecture and conventions); each worktree gets a reproducible environment; generated files are marked and staleness is caught in CI; test validity is measured (mutation), and unit and integration coverage are reported separately; static security runs in CI; project verify-* checks or hooks exist; CI is fast enough for small PRs (path filters, fan-in). | context, dev environment, codegen, mutation, coverage, unit/integration split, static security, agent configuration |
| 3 → 4: automation scaled per domain | Specs and acceptance criteria are tied to named tests; contract tests cover the boundaries between components; the API is fuzzed against its spec; post-deploy smoke checks gate releases; flow metrics are measured. | intent, contract, API fuzzing, smoke, flow metrics |

## The four questions

Every layer gets four answers. Each answer is `yes`, `partial`, `no`, `unknown` or `n/a`, and cites its evidence: a file and line, a CI job, a branch protection rule, or a command and its output. `unknown` means the evidence is missing or could not be read; it is never a guess, and it never counts as met.

| Question | Strong evidence | Weak evidence |
|---|---|---|
| **Exists?** | Config in the repo **and** the tool runs: a command the audit ran, or a CI job that runs it. | A dependency or config file only; a tool mentioned in a doc. |
| **In CI?** | A job runs the command on pull requests (trigger `pull_request` / merge requests), directly or through a resolved runner target (the scanner's `via` chain). | A keyword match in an unresolved target; only on push to the default branch, on a schedule or by hand; behind a path filter that skips most changes; a commented-out step. |
| **Blocks merge?** | Branch protection or a ruleset lists the job as a required check (read with `gh api`, with permission), or a merge queue runs it; plus a threshold where the tool has one (`fail_under`, `coverageThreshold`, Stryker `break`). | The job is not soft-fail (`continue-on-error`, `allow_failure`, `soft_fail`). Necessary, not sufficient: report `partial` without the protection rule, and `unknown` if protection could not be read. |
| **Measured?** | A number that is produced and tracked: measured by the audit (suite time, flake re-run), enforced by a threshold, or trended by a service (Codecov and the like). | A report uploaded as an artifact that nobody reads; a number in a one-off doc. |

A file merely existing is weak evidence and is scored that way.

## Layers

For each layer: what to look for, where the scanner reports it, and what strong looks like. Check kinds are the scanner's `checks` keys on CI jobs and the `commands` keys on agent docs; tool kinds are the `kind` of a `tools` entry.

### Tests and the self-check loop

- **Exists:** test files (`tests.files`, `tests.by_hint`), a test runner config (`tools`, kind `tests`), lint and format config (kinds `lint`, `format`), `pre_commit` hooks.
- **In CI:** check kinds `tests`, `lint`, `format`, `pre_commit`, `build`; `e2e` for system and end-to-end tests (kind `e2e` in `tools` too: Playwright, Cypress).
- **Measured:** the suite time, from one timed run of the documented command; flakiness, from a second run when the suite is fast. Failures on the default branch that pass when run alone point to a test isolation bug: report them.
- **Strong:** one documented command each for build, lint and test; the suite finishes in minutes; two runs agree.

### Types

- **Exists:** kind `types` in `tools` (mypy, pyright, `typescript-strict` from tsconfig `"strict": true`, phpstan, sorbet). Compiled languages (Go, Rust, Java, C#) count as typed by the compiler; say so.
- **In CI:** check kind `types` (or `build` for compiled languages).
- **Strong:** strict mode on the risky packages, not only the easy ones. Weak: type checking over less than half the code, or the riskiest packages excluded.

### Coverage, with unit and integration reported separately

- **Exists:** kind `coverage` in `tools`; `coverage-threshold` when a threshold is set.
- **In CI:** check kind `coverage`.
- **Measured:** a threshold or a coverage service.
- **Strong:** unit and integration coverage reported **separately**. A combined number overstates the code that only integration tests touch: a high total can hide almost no unit coverage, and a change whose lines are reached only by integration tests is barely checked by the fast loop. Without the split, answer `partial` at best and say what the combined number hides.

### Unit / integration split

- **Exists:** `tests.by_hint` (from directory and file names), pytest `markers`, separate CI jobs or targets for unit and integration.
- **Strong:** tests classified by their real dependencies (a test that needs a database or a network client is integration, whatever its marker), with the two suites runnable separately. Weak: markers on some tests only.

### Test validity (mutation testing)

- **Exists:** kind `mutation` in `tools` (mutmut, cosmic-ray, Stryker, PIT, cargo-mutants, go-mutesting / gremlins, mutant, Infection); `mutation-threshold` when a break threshold is set.
- **In CI:** check kind `mutation`, usually scoped to the diff and report-only at first.
- **Measured:** a mutation score per module or per diff.
- **Why it matters for agents:** coverage alone cannot show the tests are any good; a test can assert nothing and still cover every line. Mutation testing only reaches pure tests (it aborts when a test needs a database that isn't there), which is one more reason to push logic into pure code.

### API matches spec (fuzzing) and untrusted input

- **Exists:** `specs.openapi` / `specs.asyncapi`; kind `fuzz` (Schemathesis, RESTler, Jazzer, Atheris, `go test -fuzz` targets, cargo-fuzz) and kind `property` (Hypothesis, fast-check, proptest, jqwik) for parsers and anything else that takes untrusted input.
- **In CI:** check kind `fuzz`.
- **Strong:** the API is fuzzed against its own spec, where a 500 or a schema violation is a real bug, with a known-failures list where each entry has a repro (never a silent allowlist). Weak: a spec with no check that the service matches it.

### Contract tests

- **Exists:** kind `contract` (Pact files or dependency, Specmatic, Dredd, Spring Cloud Contract); `tests.by_hint.contract`.
- **In CI:** check kind `contract` (`can-i-deploy` gates a release).
- **Why:** without contract tests, two components can drift apart while each one's own tests stay green. `n/a` for a single component with no consumers.

### Post-deploy smoke checks

- **Exists:** `smoke.files`, `tests.by_hint.smoke`; check kind `smoke` in a deploy or release workflow.
- **Strong:** a smoke check that runs after every deploy and can trigger a rollback. `n/a` for libraries and tools that are not deployed.

### Static security

Three rows, each with the four questions:

- **SAST:** kind `sast` (Bandit, Semgrep, gosec, CodeQL, Brakeman, SpotBugs). Linters alone are not SAST.
- **Dependency scan:** kind `dependency_scan` (pip-audit, npm audit, osv-scanner, govulncheck, cargo audit / deny, dependency-review). Dependabot or Renovate (kind `dependency_updates`) keep versions current but are not a scan; report them separately.
- **Secret scan:** kind `secret_scan` (gitleaks, TruffleHog, detect-secrets, ggshield). A hosted secret scanning setting is outside the repo: `unknown` unless the human says.

### Intent to test

- **Exists:** `intent.ears_like` ("when X, the system shall Y" lines), `intent.acceptance_criteria`, `intent.gherkin`.
- **Strong:** specs live in the repo, criteria are in EARS form, and each criterion names the test that proves it. A reviewer checklist read only by humans is weak.

### Flow metrics

- **Exists:** `flow.ci_hints` (CI lines with check kind `flow_metrics`: DORA tooling and the like), `flow.pr_templates`; otherwise outside the repo.
- **Measured:** review effort (time to first review, review rounds), escaped defects (reverts, hotfixes, bugs traced to merged PRs), lead time (first commit or PR open to merge, merge to deploy). The audit may compute rough numbers from `gh pr list` or `git log` with permission; otherwise `unknown`.

### Runnable, reproducible dev environment

- **Exists:** `dev_env`: devcontainer, Dockerfiles, compose files, toolchain pins, lockfiles, setup scripts, task runners and their targets.
- **Strong:** a fresh worktree reaches a green test run with one documented command and pinned toolchains; no shared mutable state between worktrees (ports, databases, caches), so ten agents can run at once. Can the app be launched and observed headless?

### Context (CLAUDE.md and docs)

- **Exists:** `context.agent_docs` (CLAUDE.md, AGENTS.md and the like, nested ones included), `architecture_docs`, `adr_dirs`, `contributing`.
- **Strong:** the agent doc lists the build, test, lint and type-check commands (`commands` per doc, found in code spans and code blocks, resolved through runner targets), and those commands match what CI runs; conventions an agent would otherwise guess are written down. A doc with no commands is weak.

### Agent configuration

- **Exists:** `agent_config`: `.claude/settings*.json` permissions (`allow` / `deny` / `ask`, `defaultMode`) and hook counts per event, project skills (`verify: true` for `verify-*` skills), commands, agents, MCP servers.
- **Strong:** deny rules for destructive commands; pre-approvals that are read-only and narrow (no wildcard that can absorb a writing flag, no pattern a cloned repo could plant); hooks that run the cheap checks; `verify-*` skills an agent can run to check its own work. Report over-broad allow entries as a finding.

### Generated artifacts and codegen

- **Exists:** `codegen.generated_files` (files with a generated header), `generator_configs`, `go_generate`, `generate_targets`, `gitattributes_generated`.
- **In CI:** check kind `generated_check` (regenerate, then `git diff --exit-code`).
- **Why it matters for agents:** checked-in generators whose output drives CI break CI in ways an agent won't predict: an agent adds a file and does not rerun the generator, or a new file matches a generator glob and becomes its own CI job. Strong: generated files are marked, the regenerate command is documented, and CI fails on stale output.

## Tools by ecosystem

What to look for when a layer is missing. The scanner reports what it finds; this table is for suggesting the usual tool.

| Layer | Python | TypeScript / JavaScript | Go | Rust | JVM | Ruby |
|---|---|---|---|---|---|---|
| Types | mypy, pyright | tsc `strict` | compiler | compiler | compiler, Error Prone | Sorbet, Steep |
| Lint | Ruff, Pylint | ESLint, Biome | golangci-lint | Clippy | Checkstyle, detekt | RuboCop |
| Coverage | coverage.py, pytest-cov | c8, nyc, Vitest / Jest coverage | `go test -cover` | cargo-llvm-cov, tarpaulin | JaCoCo, Kover | SimpleCov |
| Mutation | mutmut, cosmic-ray | Stryker | gremlins, go-mutesting | cargo-mutants | PIT | mutant |
| Fuzz / property | Hypothesis, Atheris, Schemathesis | fast-check, Jazzer.js, Schemathesis | `go test -fuzz` | cargo-fuzz, proptest | Jazzer, jqwik | (property: rantly) |
| SAST | Bandit, Semgrep | Semgrep, CodeQL | gosec | Semgrep | SpotBugs, CodeQL | Brakeman |
| Dependency scan | pip-audit | npm audit, osv-scanner | govulncheck | cargo audit, cargo deny | OWASP dependency-check | bundler-audit |

Any ecosystem: gitleaks or TruffleHog (secrets), osv-scanner or Trivy (dependencies), Semgrep or CodeQL (SAST), Dependabot or Renovate (updates), pre-commit or lefthook (local hooks).

## CI capability table

Before recommending a new check, find out what the CI system can do. Fill one row per capability, each cell backed by a file reference (the scanner's `ci.capabilities`, which also looks inside scripts a job calls for annotations, dynamic pipelines and diff bases). An empty list means "not used here", not "not supported": say which.

| Capability | Why it matters | GitHub Actions | GitLab CI | Buildkite | CircleCI | Jenkins | Azure Pipelines |
|---|---|---|---|---|---|---|---|
| `fan_in` | combine N per-file jobs (diff coverage, reports) | `needs:` | `needs:`, `stages:` | `wait`, `depends_on` | `requires:` | `parallel` then a stage | `dependsOn:` |
| `artifacts` | pass coverage files or reports between jobs | `upload-artifact` / `download-artifact` | `artifacts:`, `dependencies:` | `artifact_paths`, `buildkite-agent artifact` | `persist_to_workspace`, `store_artifacts` | `stash`, `archiveArtifacts` | `PublishPipelineArtifact` |
| `soft_fail` | land a new check as report-only first | `continue-on-error:` | `allow_failure:` | `soft_fail:` | n/a | `catchError`, `unstable` | `continueOnError:` |
| `annotations` | show findings on the PR without the log | `::error`, `$GITHUB_STEP_SUMMARY` | `reports:` (junit, codequality) | `buildkite-agent annotate` | `store_test_results` | `junit`, `recordIssues` | `##vso[`, `PublishTestResults` |
| `path_filters` | skip checks a change cannot affect | `paths:`, `paths-ignore:` | `rules: changes:` | `if_changed`, monorepo-diff | path-filtering orb | `changeset` | trigger `paths:` |
| `per_job_env` | give one job its own settings or secrets | job / step `env:` | job `variables:` | step `env:` | `environment:` | `environment {}`, `withEnv` | job `variables:` |
| `diff_base` | scope diff checks to the merge base, so stacked PRs work | `github.base_ref`, `pull_request.base.sha` | `CI_MERGE_REQUEST_DIFF_BASE_SHA` | `BUILDKITE_PULL_REQUEST_BASE_BRANCH` | n/a | `CHANGE_TARGET` | `System.PullRequest.TargetBranch` |
| `dynamic_pipeline` | a generator writes the pipeline (check its globs and stale output) | `fromJSON(` matrices | `trigger:` child pipelines | `pipeline upload` | `setup: true` | n/a | n/a |

Diff coverage across N per-file jobs needs all of: a coverage file uploaded from each job, a combine step that waits on all of them and tolerates their failures, relative paths in the coverage config, and a report of how many of the N jobs reported (cached jobs upload nothing). Diff-scoped checks use the merge-base variable, not a hard-coded default branch.

## Prioritising fixes

Rank fixes by **agent impact**, then effort:

1. **Gate first.** Fixes for the current bottleneck gate come first, then the next gate. A fix two gates ahead waits, however cheap.
2. **What it unlocks.** Name what it enables: the next adoption step, a `verify-*` skill an agent can run, or the `agent-loop` specialist it makes possible (a planned agent-loop specialist, for example a mutation, fuzzing, contract or security specialist; a specialist whose tooling is missing reports BLOCKED, and this fix is how to unblock it).
3. **Flow.** Say which of review effort, escaped defects or lead time it should move, and how you would see it move.
4. **Effort.** `S`: config plus one CI step, under about an hour. `M`: about a day, including making it pass. `L`: more, or needs a decision from the team.
5. **Prior art.** Point at the closest existing job, config or script in the repo to copy (a file and line), so the fix matches the repo's shape.

Shape of every new check: opt-in locally and report-only in CI at first (`soft_fail` where the CI has it), and the default test run must not get slower. Recommend settling the hardest unknown (often: can the CI fan in, or will a generator pick up the new file?) with one throwaway draft PR before building anything out.

## Machine-readable output (`--json`)

With `--json`, the message ends with one fenced `json` block of this shape, with nothing after it, for tools such as `agent-loop` to choose specialists from. Every `evidence` entry is a `path:line`, a CI job (`path#job`), or a command and its result.

```json
{
  "schema": 1,
  "tool": "agent-ready",
  "repo": "<audited path>",
  "date": "YYYY-MM-DD",
  "step": {
    "supported": 1,
    "bottleneck": "one sentence",
    "next_gate": [{"item": "tests block merge", "met": false, "evidence": [".github/workflows/ci.yml#test"]}]
  },
  "layers": [
    {
      "layer": "types",
      "exists": {"answer": "yes", "evidence": ["pyproject.toml:12"]},
      "in_ci": {"answer": "yes", "evidence": [".github/workflows/ci.yml#types"]},
      "blocks_merge": {"answer": "unknown", "evidence": []},
      "measured": {"answer": "no", "evidence": []},
      "notes": ""
    }
  ],
  "ci_capabilities": [{"capability": "fan_in", "answer": "yes", "evidence": [".github/workflows/ci.yml:31"]}],
  "measurements": [{"what": "test suite time", "command": "pytest -q", "result": "41 s, 2 runs agree"}],
  "fixes": [
    {
      "rank": 1,
      "title": "Run mutation testing on the diff, report-only",
      "layer": "mutation",
      "gate": "2->3",
      "impact": "high",
      "effort": "M",
      "unlocks": ["a planned agent-loop mutation specialist"],
      "flow": "escaped defects",
      "prior_art": ".github/workflows/ci.yml:20",
      "evidence": ["pyproject.toml:30"]
    }
  ],
  "unknowns": [{"what": "required status checks", "how_to_settle": "gh api repos/OWNER/REPO/rules/branches/main"}]
}
```

- `layer` is one of `tests`, `types`, `coverage`, `unit_integration_split`, `mutation`, `api_fuzzing`, `contract`, `smoke`, `sast`, `dependency_scan`, `secret_scan`, `intent`, `flow_metrics`, `dev_env`, `context`, `agent_config`, `codegen`.
- `answer` is one of `yes`, `partial`, `no`, `unknown`, `n/a`.
- `capability` is one of the CI capability table's keys.
- `step.supported` is 0 to 4; `gate` is `0->1`, `1->2`, `2->3` or `3->4`; `impact` is `high`, `medium` or `low`; `effort` is `S`, `M` or `L`.
