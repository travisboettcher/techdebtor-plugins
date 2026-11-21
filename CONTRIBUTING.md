# Contributing

Thanks for helping. This repository is a Claude Code plugin marketplace: each plugin lives in `plugins/<name>/` and is listed in `.claude-plugin/marketplace.json`. Only generic, reusable plugins belong here; anything specific to one project or one person's setup stays in that project's `.claude/` or in `~/.claude/`.

Agents working in this repository read [`CLAUDE.md`](CLAUDE.md), the short version of this file.

## Adding a plugin

1. **Layout.** Create `plugins/<name>/` with:
   - `.claude-plugin/plugin.json`: name, version, description, author, `"license": "MIT"`, repository, keywords.
   - `skills/<skill>/SKILL.md` (with `references/` for detail loaded on demand) and `agents/*.md`, as the plugin needs.
   - `scripts/` for Python helpers (standard library only) and `tests/` for their pytest suite.
   - `docs/DESIGN.md`: the contract (formats, rules, what each part may and may not do).
   - `README.md` (what it does, install, use) and `CHANGELOG.md`.
2. **Marketplace entry.** Add the plugin to `.claude-plugin/marketplace.json` with `"source": "./plugins/<name>"`, the same description as `plugin.json` and a category.
3. **CI.** In `.github/workflows/ci.yml`, run the plugin's tests and `claude plugin validate plugins/<name>`.
4. **Token budget.** Measure the plugin's always-on cost (below) and add a ceiling about 15-20% above it to `.github/token-budgets.json`.
5. **Root README.** Add a row to the plugin table.

## Changing a plugin

- **Contract first.** If the change alters behaviour, formats or rules, update `docs/DESIGN.md` first, then the skills, agents, scripts, README and CHANGELOG to match. A rule stated in two files must say the same thing in both.
- **Tests first.** For scripts, write a failing test, then the code. Scripts that read untrusted input (transcripts, records, CLI output) must parse it in linear time; add a test with a large hostile input.
- **Least privilege.** A skill's `allowed-tools` and an agent's `tools` list only what the job needs.
- **Validators.** `claude plugin validate .` and `claude plugin validate plugins/<name>` must pass.
- **Token cost.** Run `python3 .github/scripts/token_budget.py` and put the always-on cost in the pull request description when it changes. A change that needs a higher ceiling raises it in `.github/token-budgets.json` and says why.
- **CHANGELOG.** Add a line under `## Unreleased` at the top of the plugin's `CHANGELOG.md` (create the heading if it is missing); the release moves it under the version.
- Shipped files contain nothing specific to one project, person or machine, and no issue or pull request numbers.
- Heavy jobs (full suites, builds, mutation testing) run one at a time. Running several in parallel can starve the machine and its network.

Run a plugin's tests from its directory:

```
cd plugins/<name>
python -m pytest -q
```

## Prose style

[Vale](https://vale.sh) lints every tracked Markdown file in CI (`.github/workflows/prose.yml`). `.vale.ini` at the root picks one of two styles by path:

| Style | Files | What it checks |
|---|---|---|
| Prompt | `CLAUDE.md`, `plugins/*/skills/**`, `plugins/*/agents/*.md`, `plugins/*/docs/specialists/*.md`, `plugins/*/docs/examples/**` | What weakens an instruction to a model: hedges ("try to", "if possible", "consider"), politeness ("please"), filler ("simply", "just", "in order to"), "you should" instead of the imperative, "etc.", ALL-CAPS words outside an allowlist of protocol words and acronyms, and sentences over 60 words. Plus repeated words. |
| Docs | every other Markdown file: READMEs, `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/*.md` | Vale's spelling and repeated-word checks, and a subset of [write-good](https://github.com/vale-cli/write-good) and [proselint](https://github.com/vale-cli/proselint) (hedging, clichés, redundancy, "very", sentences starting with "So"). |

Code spans, fenced code blocks and YAML front matter are never linted. Most rules are warnings: CI annotates them on the pull request but does not fail. Errors fail CI; they are kept to rules that are always right (repeated words; "please", "kindly", "simply", "basically" and "in order to" in prompts).

The styles live in `.github/vale/styles/`: `Prompt/` is this repository's own; `write-good/` and `proselint/` are copied unmodified from their releases (v0.5.0 and v0.4.0) with their licenses, and `.vale.ini` sets their levels. Nothing is downloaded at lint time; do not run `vale sync`.

**Run it locally** with the same pinned Vale, 3.28.1, from [its releases](https://github.com/vale-cli/vale/releases/tag/v3.28.1). Check the archive against the release's `vale_3.28.1_checksums.txt`, unpack it outside the repository, then from the repository root (paths must be relative: the styles are chosen by path):

```
git ls-files -z '*.md' | xargs -0 vale
```

**Add vocabulary.** When Vale's spelling check flags a correct term (a tool name, a coined word such as `worktree`), add it to `.github/vale/styles/config/vocabularies/Repo/accept.txt`, one regular expression per line, kept in alphabetical order; `[Ww]orktrees?` accepts the capitalised and plural forms. For a new protocol word or acronym that the Prompt style calls shouting, add it to the `exceptions` in `.github/vale/styles/Prompt/Shouting.yml`. Tokens joined by underscores, such as `PLAN_READY`, are never flagged.

## Token budget

Every plugin's always-on cost (its skill and agent descriptions, loaded into every session) has a ceiling in `.github/token-budgets.json`. CI measures it with `claude plugin details` from Claude Code 2.1.322, signed out; run the same check locally with:

```
python3 .github/scripts/token_budget.py
```

It runs the CLI signed out in a fresh home directory, because a signed-in CLI estimates a higher cost than CI does. A plugin whose directory is not on the branch is skipped.

## Pull requests

- Keep pull requests small: one behaviour each, tests alongside. When a change needs several, stack them with [`gh stack`](https://github.com/github/gh-stack) (`gh extension install github/gh-stack`), each based on the one below.
- Never push to `main`; it changes only through reviewed pull requests. The repository's ruleset requires one approving review, and a push dismisses earlier approvals.
- CI runs on every pull request: each plugin's tests, `claude plugin validate` on the marketplace and each plugin, Vale, the token budget, and the tests of the scripts under `.github/scripts/`. Keep it green.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
