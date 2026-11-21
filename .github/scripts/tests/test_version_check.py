"""Tests for version_check.py: unit tests for the parsers, and end-to-end
runs against throwaway git repositories with an `origin` remote."""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "version_check.py"
_spec = importlib.util.spec_from_file_location("version_check", SCRIPT)
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


# --- semver -----------------------------------------------------------------

@pytest.mark.parametrize("text", ["0.1.0", "1.2.3", "10.20.30", "1.0.0-alpha.1", "1.0.0+build.5", "1.0.0-rc.1+b"])
def test_parse_semver_accepts_valid(text):
    assert vc.parse_semver(text) is not None


@pytest.mark.parametrize(
    "text",
    ["", "1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "v1.2.3", "1.2.3-", "1.2.3-01", "1.2.3-a..b", "1.2.3+", " 1.2.3", "1.2.x", None, 1],
)
def test_parse_semver_rejects_invalid(text):
    assert vc.parse_semver(text) is None


@pytest.mark.parametrize(
    "lower, higher",
    [
        ("0.1.0", "0.1.1"),
        ("0.1.9", "0.2.0"),
        ("0.9.0", "0.10.0"),
        ("1.9.9", "2.0.0"),
        ("1.0.0-alpha", "1.0.0"),
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
        ("1.0.0-alpha.2", "1.0.0-alpha.10"),
        ("1.0.0-beta", "1.0.0-rc.1"),
    ],
)
def test_semver_ordering(lower, higher):
    assert vc.parse_semver(lower) < vc.parse_semver(higher)
    assert not vc.parse_semver(higher) < vc.parse_semver(lower)


def test_build_metadata_does_not_count():
    assert vc.parse_semver("1.0.0+a") == vc.parse_semver("1.0.0+b")


def test_parse_semver_is_linear_on_long_input():
    start = time.perf_counter()
    for text in ("1.2.3-" + "a." * 100_000 + "!", "9" * 200_000, "1.2.3-" + "-" * 200_000 + "+" * 2):
        vc.parse_semver(text)
    assert time.perf_counter() - start < 1.0


# --- changelog --------------------------------------------------------------

def test_changelog_sections_in_order_and_ignores_code_fences():
    text = "# Changelog\n\n## Unreleased\n\n```\n## 9.9.9\n```\n## [0.2.0] - 2026-01-01\n- x\n### Sub\n## 0.1.0\n"
    assert vc.changelog_sections(text) == ["unreleased", "0.2.0", "0.1.0"]


def test_changelog_top_must_be_version_when_base_is_default():
    assert vc.changelog_problem("## 0.1.1\n## 0.1.0\n", "0.1.1", stacked=False) is None
    assert "top section" in vc.changelog_problem("## Unreleased\n## 0.1.1\n", "0.1.1", stacked=False)
    assert "top section" in vc.changelog_problem("## 0.1.0\n## 0.1.1\n", "0.1.1", stacked=False)


def test_changelog_unreleased_allowed_above_when_stacked():
    assert vc.changelog_problem("## Unreleased\n## 0.1.1\n", "0.1.1", stacked=True) is None
    assert vc.changelog_problem("## 0.1.1\n", "0.1.1", stacked=True) is None
    assert vc.changelog_problem("## 0.1.0\n## 0.1.1\n", "0.1.1", stacked=True) is not None


def test_changelog_missing_section():
    assert "no `## 0.1.1`" in vc.changelog_problem("## 0.1.0\n", "0.1.1", stacked=True)
    assert vc.changelog_problem("", "0.1.1", stacked=False) is not None


def test_changelog_parse_is_linear_on_long_input():
    start = time.perf_counter()
    vc.changelog_sections("## " + " " * 200_000 + "x\n" + "#" * 200_000 + "\n" + "```" * 50_000)
    assert time.perf_counter() - start < 1.0


# --- shipped paths ----------------------------------------------------------

@pytest.mark.parametrize(
    "rel, shipped",
    [
        ("skills/lead/SKILL.md", True),
        (".claude-plugin/plugin.json", True),
        ("CHANGELOG.md", True),
        ("scripts/x.py", True),
        ("tests/test_x.py", False),
        ("evals/case.json", False),
        ("pytest.ini", False),
        (".venv/bin/python", False),
        ("scripts/__pycache__/x.cpython-313.pyc", False),
        (".pytest_cache/v/cache", False),
        ("scripts/x.pyc", False),
        ("docs/tests/notes.md", True),
    ],
)
def test_is_shipped(rel, shipped):
    assert vc.is_shipped(rel) is shipped


@pytest.mark.parametrize(
    "source, name",
    [("./plugins/a", "a"), ("./plugins/a-b_c.1/", "a-b_c.1"), ("../plugins/a", None), ("./plugins/..", None),
     ("./plugins/a/b", None), ("plugins/a", None), ({"source": "github", "repo": "x/y"}, None), ("./plugins/", None)],
)
def test_local_plugin_dir(source, name):
    assert vc.local_plugin_dir(source) == name


# --- end to end against real git repos ---------------------------------------

def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True).stdout


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def set_plugin(root, name, version, changelog=None):
    write(root, f"plugins/{name}/.claude-plugin/plugin.json", json.dumps({"name": name, "version": version}))
    write(root, f"plugins/{name}/CHANGELOG.md", changelog if changelog is not None else f"# Changelog\n\n## {version}\n")


def set_marketplace(root, names, extra=()):
    plugins = [{"name": n, "source": f"./plugins/{n}"} for n in names] + list(extra)
    write(root, ".claude-plugin/marketplace.json", json.dumps({"name": "m", "plugins": plugins}))


def commit(root, msg="c"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    """A clone whose origin/main has plugin `p` at 0.1.0; HEAD is a feature branch off it."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "main")
    set_marketplace(upstream, ["p"])
    set_plugin(upstream, "p", "0.1.0")
    write(upstream, "plugins/p/skills/s/SKILL.md", "v1\n")
    commit(upstream)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(upstream), str(clone))
    git(clone, "checkout", "-q", "-b", "feature")
    return clone


def run(repo, *args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        env=GIT_ENV, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_unchanged_plugin_passes(repo):
    write(repo, "README.md", "x\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_shipped_change_without_bump_fails(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1
    assert "p" in out and "0.1.0" in out and "bump" in out


def test_shipped_change_with_bump_and_changelog_passes(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.1.1", "# Changelog\n\n## 0.1.1\n- x\n\n## 0.1.0\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_tests_only_change_needs_no_bump(repo):
    write(repo, "plugins/p/tests/test_a.py", "x\n")
    write(repo, "plugins/p/evals/e.json", "{}\n")
    write(repo, "plugins/p/pytest.ini", "[pytest]\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_moving_shipped_file_into_tests_counts_as_shipped_change(repo):
    (repo / "plugins/p/tests").mkdir()
    git(repo, "mv", "plugins/p/skills/s/SKILL.md", "plugins/p/tests/SKILL.md")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1, out


def test_version_lower_or_equal_fails(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.0.9")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1 and "0.0.9" in out and "0.1.0" in out


def test_invalid_version_fails(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.2")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1 and "semver" in out


def test_bump_without_changelog_section_fails(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.1.1", "# Changelog\n\n## 0.1.0\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1 and "CHANGELOG" in out


def test_unreleased_on_top_fails_against_default_but_passes_stacked(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.1.1", "## Unreleased\n- y\n\n## 0.1.1\n- x\n")
    commit(repo)
    assert run(repo, "--base-ref", "main")[0] == 1
    assert run(repo, "--base-ref", "some-feature")[0] == 0
    # no base (a push) is judged like a PR into the default branch
    assert run(repo)[0] == 1


def test_compares_against_default_branch_not_pr_base(repo):
    # A stacked branch: the branch below bumped to 0.1.1; this one changes
    # the plugin again. Against main, 0.1.1 > 0.1.0 is enough.
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    set_plugin(repo, "p", "0.1.1")
    commit(repo)
    git(repo, "checkout", "-q", "-b", "upper")
    write(repo, "plugins/p/skills/s/SKILL.md", "v3\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "feature")
    assert code == 0, out


def test_main_moved_ahead_judged_on_this_branchs_changes(repo, tmp_path):
    # main gets an unrelated plugin change + bump after the branch point;
    # a branch that never touched the plugin must not be asked to bump.
    upstream = tmp_path / "upstream"
    write(upstream, "plugins/p/skills/s/SKILL.md", "main-v2\n")
    set_plugin(upstream, "p", "0.1.1")
    commit(upstream)
    git(repo, "fetch", "-q", "origin")
    write(repo, "README.md", "x\n")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out
    # ...but a branch that did change it must beat main's new version.
    write(repo, "plugins/p/skills/s/other.md", "x\n")
    set_plugin(repo, "p", "0.1.1")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1 and "0.1.1" in out


def test_new_plugin_passes_with_any_valid_version(repo):
    set_marketplace(repo, ["p", "q"])
    set_plugin(repo, "q", "3.0.0")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_new_plugin_with_invalid_version_fails(repo):
    set_marketplace(repo, ["p", "q"])
    set_plugin(repo, "q", "latest")
    commit(repo)
    assert run(repo, "--base-ref", "main")[0] == 1


def test_non_local_sources_are_skipped(repo):
    set_marketplace(repo, ["p"], extra=[{"name": "r", "source": {"source": "github", "repo": "a/b"}}])
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_uncommitted_changes_are_ignored(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "dirty\n")
    code, out = run(repo, "--base-ref", "main")
    assert code == 0, out


def test_default_branch_option_and_missing_ref(repo):
    code, out = run(repo, "--default-branch", "nope")
    assert code == 2 and "nope" in out


def test_default_branch_falls_back_to_origin_head(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    commit(repo)
    git(repo, "remote", "set-head", "origin", "main")
    code, out = run(repo, "--default-branch", "")
    assert code == 1, out


def test_not_a_git_repo_exits_2(tmp_path):
    write(tmp_path, ".claude-plugin/marketplace.json", json.dumps({"plugins": []}))
    code, out = run(tmp_path)
    assert code == 2


def test_malformed_plugin_json_fails(repo):
    write(repo, "plugins/p/skills/s/SKILL.md", "v2\n")
    write(repo, "plugins/p/.claude-plugin/plugin.json", "{not json")
    commit(repo)
    code, out = run(repo, "--base-ref", "main")
    assert code == 1 and "plugin.json" in out
