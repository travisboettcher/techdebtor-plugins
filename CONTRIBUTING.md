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

[Vale](https://vale.sh) lints every tracked Markdown file in CI (`.github/workflows/prose.yml`). `.vale.ini` at the root picks the rules by path, from upstream packages used as released:

| Files | Packages | What they check |
|---|---|---|
| Model-facing: `CLAUDE.md`, `plugins/*/skills/**`, `plugins/*/agents/**`, `plugins/*/commands/**`, `plugins/*/docs/specialists/*.md`, `plugins/*/docs/examples/**`, and the `description` and `argument-hint` of every skill, agent and command | [Prompts](https://github.com/jdkato/prompts), the core of [Voices](https://github.com/jdkato/voices) plus one rule of its Direct voice (`Direct.Hedging`), and `Repo.SentenceLength` | Advice instead of instructions (`you should`, `please`, `try to`, `make sure to` opening a sentence), hedges, verbs that name no action (`handle`, `ensure`), too much shouting, contradictions, dates that will go stale, backslash paths, long sections and files, skill front matter (name, description length, third person, a "Use when" trigger), inflated words, throat-clearing, weasel attribution, recap endings, sentences over 60 words, repeated words. |
| Human-facing: every other Markdown file: READMEs, `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/*.md` (including `DESIGN.md` and `categories.md`: skills read them too, but they are written for people first) | [proselint](https://github.com/vale-cli/proselint) and the core of Voices | Spelling, repeated words, clichés, redundancy, hedging, jargon, inflated words and the rest of proselint. |

Code spans, fenced code blocks and YAML front matter are never linted (Prompts' front matter rules read the raw file); a word you are writing about rather than using goes in a code span (write `` `please` ``, not "please"), or a rule fires on it. The model-facing front matter values are linted as prose too: `.github/scripts/frontmatter_prose.py` copies each skill's, agent's and command's `description` and `argument-hint` into a scratch directory, Vale lints them with the model-facing rules, and the alerts point back at the source line. Errors fail CI; warnings are annotated on the pull request and do not fail it, but keep the count at zero: fix a warning in text you touch, or turn the rule off as below.

**The packages.** `.github/vale/packages.json` pins each one to a versioned release zip and its sha256: Prompts v0.1.1, Voices v0.2.0, Std v0.2.0 (not enabled; `Repo.SentenceLength` extends its rule) and proselint v0.4.0. `.github/scripts/vale_packages.py` downloads them, checks each against its pin, and unpacks it into `.github/vale/styles/`, which is gitignored except for this repository's own `Repo/` style and `config/vocabularies/Repo/`. Never run `vale sync`, and never use a `latest` URL. To upgrade a package, change its version, URL and sha256 together (the sha256 is the `digest` that `gh release view <tag> -R <repo> --json assets` shows; check it against the zip you download) and run Vale over the repository before and after.

**Run it locally** with the same pinned Vale, 3.28.1, from [its releases](https://github.com/vale-cli/vale/releases/tag/v3.28.1). Check the archive against the release's `vale_3.28.1_checksums.txt` and unpack it outside the repository. Then, from the repository root (paths must be relative: the rules are chosen by path):

```
python3 .github/scripts/vale_packages.py
git ls-files -z '*.md' | xargs -0 vale
```

`vale_packages.py` does nothing when the pinned versions are already installed. For the front matter values:

```
out=$(mktemp -d)
python3 .github/scripts/frontmatter_prose.py extract --out "$out"
(cd "$out" && find plugins -name '*.md' -print0 | xargs -0 vale --config "$OLDPWD/.vale.ini")
```

The alerts name the scratch copies (`SKILL.description.md`, line 1 for the first line of the value); `.github/workflows/prose.yml` maps them back to the source.

**Turn a rule off** for the files it misfires on with `Package.Rule = NO` (or change its level with `= warning`) in the matching section of `.vale.ini`, with a one-line comment saying why. A section can name a narrower glob: agents and the skills that set `disable-model-invocation: true` turn off `Prompts.Trigger` that way, and a new user-only skill adds its path there. For one passage, wrap it in `<!-- vale Package.Rule = NO -->` and `<!-- vale Package.Rule = YES -->`. Never edit a package's files: they are replaced on every install.

**Add vocabulary.** When Vale's spelling check flags a correct term (a tool name, a coined word such as `worktree`), add it to `.github/vale/styles/config/vocabularies/Repo/accept.txt`, one regular expression per line, kept in alphabetical order; `[Ww]orktrees?` accepts the capitalised and plural forms.

## Token budget

Every plugin's always-on cost (its skill and agent descriptions, loaded into every session) has a ceiling in `.github/token-budgets.json`. CI measures it with `claude plugin details` from Claude Code 2.1.322, signed out; run the same check locally with:

```
python3 .github/scripts/token_budget.py
```

It runs the CLI signed out in a fresh home directory, because a signed-in CLI estimates a higher cost than CI does. A plugin whose directory is not on the branch is skipped.

## Pull requests

- Keep pull requests small: one behaviour each, tests alongside. When a change needs several, stack them with [`gh stack`](https://github.com/github/gh-stack) (`gh extension install github/gh-stack`), each based on the one below.
- `main` changes only through pull requests, for everyone: the repository's ruleset blocks direct pushes, force pushes and deleting the branch. A pull request needs one approving review, and a new push dismisses earlier approvals. The owner's admin role can merge a pull request without an approval.
- CI runs on every pull request: each plugin's tests, `claude plugin validate` on the marketplace and each plugin, Vale, the token budget, and the tests of the scripts under `.github/scripts/`. No status check is required by the ruleset yet, so check that CI is green before merging.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
