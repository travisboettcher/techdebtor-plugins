# techdebtor plugins

Claude Code plugins from [techdebtor.io](https://techdebtor.io).

```
/plugin marketplace add travisboettcher/techdebtor-plugins
/plugin install <plugin>@techdebtor
```

| Plugin | What it does |
|---|---|
| [`agent-loop`](plugins/agent-loop) | An agent graph that improves itself: `/agent-loop:lead` runs test-writer and implementer agents, then verification and review specialists chosen per change, and records what each caught; `/agent-loop:retro` turns recurring mistakes into rules and checks that they worked. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): adding or changing a plugin, the prose style that CI checks with Vale, token budgets, and how pull requests work. Only generic, reusable plugins belong here.

## Releasing

`claude plugin update` only installs a new release when a plugin's `version` changes, so CI (`.github/scripts/version_check.py`) fails a change to a plugin's shipped files (anything under `plugins/<name>/` except `tests/`, `evals/`, `pytest.ini` and its top-level `README.md` and `CHANGELOG.md`) unless `version` in its `plugin.json` is valid semver and greater than on `main`. Each plugin's `CHANGELOG.md` needs a `## <version>` section for the current version, at the top; a PR stacked on another branch may keep an `## Unreleased` section above it until it targets `main`. Run it locally with `python .github/scripts/version_check.py` after `git fetch origin`.

## License

MIT
