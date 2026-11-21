"""token_budget.py fails when a plugin's always-on token cost exceeds its ceiling."""

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import token_budget as tb  # noqa: E402

DETAILS = textwrap.dedent("""\
    {name} 0.2.0
      Description: Something.
      Source: {name}@inline

    Projected token cost
      Always-on:   {cost} tok   added to every session

    Per-component (rounded)
      component             always-on  on-invoke
      lead                        ~60      ~5.6k
    """)


@pytest.mark.parametrize("cost, expected", [("~1,036", 1036), ("~188", 188), ("1036", 1036),
                                             ("~1.2k", 1200), ("~12k", 12000), ("~0", 0)])
def test_parse_always_on(cost, expected):
    assert tb.parse_always_on(DETAILS.format(name="p", cost=cost)) == expected


def test_parse_strips_ansi_colour():
    text = DETAILS.format(name="p", cost="\x1b[1m~1,036\x1b[0m").replace("Always-on:", "\x1b[2mAlways-on:\x1b[0m")
    assert tb.parse_always_on(text) == 1036


@pytest.mark.parametrize("text", ["", "Always-on: lots", "Plugin \"p\" not found.", "Always-on:   ~ tok",
                                  "Always-on:   ~1,036 tok\nAlways-on:   ~9 tok"])
def test_parse_refuses_what_it_cannot_read(text):
    with pytest.raises(ValueError):
        tb.parse_always_on(text)


def test_parse_is_linear_time():
    text = "Always-on:" + " " * 200_000 + "~" + "1," * 100_000 + "x"
    start = time.perf_counter()
    with pytest.raises(ValueError):
        tb.parse_always_on(text)
    assert time.perf_counter() - start < 2


@pytest.fixture
def repo(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / "plugins" / "alpha").mkdir(parents=True)
    write_marketplace(tmp_path, [{"name": "alpha", "source": "./plugins/alpha"},
                                 {"name": "beta", "source": "./plugins/beta"}])
    (tmp_path / "budgets.json").write_text(json.dumps({"always_on_tokens": {"alpha": 1200, "beta": 220}}))
    return tmp_path


def write_marketplace(root, plugins):
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "m", "plugins": plugins}))


def fake_claude(tmp_path, costs, exit_code=0):
    """A stand-in for the claude CLI: prints `plugin details` for the plugin named last."""
    script = tmp_path / "fake_claude.py"
    script.write_text(textwrap.dedent(f"""\
        import sys
        args = sys.argv[1:]
        assert args[0] == "--plugin-dir" and args[2:5] == ["plugin", "details", "--"], args
        name = args[5]
        print({DETAILS!r}.format(name=name, cost={costs!r}[name]))
        sys.exit({exit_code})
        """))
    return f"{sys.executable} {script}"


def check(repo, claude):
    return tb.main(["--root", str(repo), "--budgets", str(repo / "budgets.json"), "--claude", claude])


def test_under_budget_passes_and_missing_plugin_dir_is_skipped(repo, capsys):
    code = check(repo, fake_claude(repo, {"alpha": "~1,036"}))
    out = capsys.readouterr().out
    assert code == 0
    assert "alpha: always-on ~1036 tok, ceiling 1200" in out
    assert "::notice title=token budget::beta: plugins/beta is not on this branch; skipped" in out


def test_over_budget_fails(repo, capsys):
    code = check(repo, fake_claude(repo, {"alpha": "~1,201"}))
    out = capsys.readouterr().out
    assert code == 1
    assert "::error title=token budget::alpha: always-on ~1201 tok exceeds its ceiling 1200" in out


def test_exactly_at_the_ceiling_passes(repo, capsys):
    assert check(repo, fake_claude(repo, {"alpha": "~1,200"})) == 0


def test_a_plugin_without_a_budget_fails(repo, capsys):
    (repo / "budgets.json").write_text(json.dumps({"always_on_tokens": {"beta": 220}}))
    assert check(repo, fake_claude(repo, {"alpha": "~10"})) == 1
    assert "alpha has no ceiling" in capsys.readouterr().out


def test_a_failing_cli_fails(repo, capsys):
    assert check(repo, fake_claude(repo, {"alpha": "~10"}, exit_code=1)) == 1
    assert "::error title=token budget::alpha: `plugin details` exited 1" in capsys.readouterr().out


def test_unparseable_details_fail(repo, capsys):
    assert check(repo, fake_claude(repo, {"alpha": "lots"})) == 1
    assert "could not read the always-on cost" in capsys.readouterr().out


def test_a_source_outside_the_repo_or_not_local_fails(repo, capsys):
    write_marketplace(repo, [{"name": "alpha", "source": "./plugins/../../elsewhere"},
                             {"name": "gamma", "source": {"source": "github", "repo": "o/r"}}])
    (repo / "budgets.json").write_text(json.dumps({"always_on_tokens": {"alpha": 1, "gamma": 1}}))
    assert check(repo, fake_claude(repo, {})) == 1
    out = capsys.readouterr().out
    assert "alpha: source ./plugins/../../elsewhere is outside the repository" in out
    assert "::notice title=token budget::gamma: source is not a local path; skipped" in out


@pytest.mark.parametrize("budgets", ['{"always_on_tokens": {"alpha": "1200"}}', '{"always_on_tokens": {"alpha": -1}}',
                                     '{"other": {}}', "not json", '{"always_on_tokens": {"alpha": true}}'])
def test_bad_budget_files_fail(repo, capsys, budgets):
    (repo / "budgets.json").write_text(budgets)
    assert check(repo, fake_claude(repo, {"alpha": "~1"})) == 2
    assert "::error title=token budget::" in capsys.readouterr().out


def test_plugin_names_are_passed_as_arguments_not_shell(repo, capsys):
    write_marketplace(repo, [{"name": "alpha; touch pwned", "source": "./plugins/alpha"}])
    (repo / "budgets.json").write_text(json.dumps({"always_on_tokens": {"alpha; touch pwned": 1200}}))
    assert check(repo, fake_claude(repo, {"alpha; touch pwned": "~5"})) == 0
    assert not (repo / "pwned").exists()


def test_the_cli_runs_signed_out_in_a_fresh_home(repo, capsys, monkeypatch, tmp_path):
    # A signed-in CLI estimates a different cost than CI's signed-out one; local runs must match CI.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "real-config"))
    seen = tmp_path / "seen.json"
    script = tmp_path / "env_claude.py"
    script.write_text(textwrap.dedent(f"""\
        import json, os, sys
        json.dump(dict(os.environ), open({str(seen)!r}, "w"))
        print({DETAILS!r}.format(name=sys.argv[-1], cost="~5"))
        """))
    assert check(repo, f"{sys.executable} {script}") == 0
    env = json.loads(seen.read_text())
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["HOME"] != str(Path.home()) and env["CLAUDE_CONFIG_DIR"].startswith(env["HOME"])
    assert not Path(env["HOME"]).exists()


def test_a_name_starting_with_a_dash_is_never_an_option(repo, capsys):
    write_marketplace(repo, [{"name": "--help", "source": "./plugins/alpha"}])
    (repo / "budgets.json").write_text(json.dumps({"always_on_tokens": {"--help": 1200}}))
    assert check(repo, fake_claude(repo, {"--help": "~5"})) == 0
