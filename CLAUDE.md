# techdebtor-plugins

A public Claude Code plugin marketplace. Humans start with `CONTRIBUTING.md`; this file is the short version for agents working in this repo.

## Layout

- `.claude-plugin/marketplace.json`: the marketplace; one entry per plugin.
- `plugins/<name>/`: one plugin. `.claude-plugin/plugin.json`, `skills/<skill>/SKILL.md` (and `references/`), `agents/*.md`, `commands/*.md`, `scripts/` (Python, standard library only), `tests/` (pytest), `docs/` (`docs/DESIGN.md` is the contract), `README.md`, `CHANGELOG.md`.
- `.github/workflows/ci.yml` (tests, manifests) and `prose.yml` (Vale, token budget); `.github/scripts/` with its tests; `.github/token-budgets.json`; `.vale.ini`, `.github/vale/packages.json` (pinned Vale packages) and `.github/vale/styles/` (gitignored except `Repo/` and the vocabulary).
- `.claude/runs/` holds local run records: gitignored, never committed.

## Rules

- A plugin's `docs/DESIGN.md` is its contract. Change the contract first, then the code, skills and agents to match it.
- Shipped files are generic: nothing specific to one project, person, machine or setup, and no issue or pull request numbers.
- No contradictions across files: when you change a rule, find every file that states it (README, DESIGN, skills, agents, CHANGELOG) and update them together. The doc-consistency tests catch some drift, not all.
- Least privilege: `allowed-tools` in skills and `tools` in agents list only what the job needs.
- Namespaced names: refer to a plugin's skills and agents as `<plugin>:<name>`.
- Scripts that read untrusted input use linear-time parsing: no nested or adjacent unbounded quantifiers; add a timing test.
- Tests first for scripts: write a failing test, then the code.
- Heavy jobs (full suites, builds, mutation testing) never run in parallel: run each through `python3 plugins/agent-loop/scripts/heavy_lock.py --label <name> -- bash -c '<command>'`.
- Never push to or merge `main`. Work on a branch; ship small pull requests, stacked with `gh stack` when they depend on each other.
- Every change to a plugin gets a line under "Unreleased" in its `CHANGELOG.md`.

## Verify

From the repo root unless noted; one at a time.

- Tests: `cd plugins/<name> && python -m pytest -q`; the repo's scripts: `python -m pytest -q .github/scripts/tests`.
- Manifests: `claude plugin validate .` and `claude plugin validate plugins/<name>`.
- Token cost: `python3 .github/scripts/token_budget.py` (ceilings in `.github/token-budgets.json`); report the always-on cost in the pull request when it changes.
- Prose: `python3 .github/scripts/vale_packages.py` (installs the pinned Prompts, Voices, Std and proselint packages), then `git ls-files -z '*.md' | xargs -0 vale` with Vale 3.28.1 (front matter: see `CONTRIBUTING.md`). Errors fail CI; fix warnings in text you touch. Put a word you write about in a code span (`` `please` ``), or it trips the rules. Turn a misfiring rule off with `Package.Rule = NO` in `.vale.ini`, with a comment saying why; never edit the packages or run `vale sync`.
