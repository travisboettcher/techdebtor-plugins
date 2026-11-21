# techdebtor plugins

Claude Code plugins from [techdebtor.io](https://techdebtor.io).

```
/plugin marketplace add travisboettcher/techdebtor-plugins
/plugin install <plugin>@techdebtor
```

| Plugin | What it does |
|---|---|
| [`agent-loop`](plugins/agent-loop) | An agent graph that improves itself: `/agent-loop:lead` runs implementer, tester and reviewer agents and records what each caught; `/agent-loop:retro` turns recurring mistakes into rules and checks that they worked. |

## Adding a plugin

Each plugin lives in `plugins/<name>/` with its own `.claude-plugin/plugin.json` and README, and an entry in `.claude-plugin/marketplace.json`. Check with `claude plugin validate .` and `claude plugin validate plugins/<name>`. Only generic, reusable plugins belong here; anything specific to one project or one person's setup stays in that project's `.claude/` or in `~/.claude/`.

## License

MIT
