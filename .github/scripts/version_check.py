#!/usr/bin/env python3
"""Check that every changed plugin carries a version bump and a changelog entry.

`claude plugin update` only picks up a release when plugin.json's `version`
changes, so a plugin change merged without a bump never reaches installed
users. For every plugin in .claude-plugin/marketplace.json whose source is
`./plugins/<name>`:

- If its shipped files (everything under plugins/<name>/ except tests/,
  evals/, pytest.ini, .venv, caches and the top-level README.md and
  CHANGELOG.md) changed on this branch since it left
  the default branch, its version must be valid semver and strictly greater
  than the default branch's (a plugin new on this branch needs only a valid
  version). This compares against the default branch, not the PR's base, so
  a stacked PR is judged on what would reach the default branch.
- Its CHANGELOG.md must have a `## <version>` section for the current
  version, and it must be the top section, except that a stacked PR (base is
  not the default branch) may keep one `## Unreleased` section above it.

Exit 0: all good. Exit 1: a plugin fails the rule. Exit 2: cannot check.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REMOTE = "origin"
FALLBACK_DEFAULT_BRANCH = "main"
PLUGINS_DIR = "plugins"
NOT_SHIPPED_TOP = {"tests", "evals", "pytest.ini", ".venv", "README.md", "CHANGELOG.md"}
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}
CACHE_SUFFIXES = (".pyc", ".pyo")


class CannotCheck(Exception):
    pass


# --- semver -----------------------------------------------------------------

def _numeric(ident: str) -> bool:
    return ident.isascii() and ident.isdigit() and (ident == "0" or not ident.startswith("0"))


def _ident_ok(ident: str) -> bool:
    return bool(ident) and all(c.isascii() and (c.isalnum() or c == "-") for c in ident)


def parse_semver(text):
    """Return a sortable precedence key for a semver string, or None if invalid.

    Build metadata is validated but ignored for precedence. Linear time.
    """
    if not isinstance(text, str):
        return None
    core, plus, build = text.partition("+")
    if plus and not all(_ident_ok(i) for i in build.split(".")):
        return None
    core, dash, pre = core.partition("-")
    parts = core.split(".")
    if len(parts) != 3 or not all(_numeric(p) for p in parts):
        return None
    major, minor, patch = (int(p) for p in parts)
    if not dash:
        # A release sorts after any prerelease of the same core.
        return (major, minor, patch, 1, ())
    idents = pre.split(".")
    key = []
    for ident in idents:
        if not _ident_ok(ident):
            return None
        if ident.isascii() and ident.isdigit():
            if not _numeric(ident):
                return None
            key.append((0, int(ident), ""))
        else:
            key.append((1, 0, ident))
    return (major, minor, patch, 0, tuple(key))


# --- changelog --------------------------------------------------------------

def changelog_sections(text: str) -> list[str]:
    """Level-2 headings' first word, lowercased, brackets stripped, in order.

    Headings inside fenced code blocks are ignored.
    """
    sections = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not line.startswith("## "):
            continue
        words = line[3:].split(maxsplit=1)
        if words:
            sections.append(words[0].strip("[]").lower())
    return sections


def changelog_problem(text: str, version: str, stacked: bool) -> str | None:
    """Why the changelog does not fit `version`, or None if it does."""
    sections = changelog_sections(text)
    want = version.lower()
    if want not in sections:
        return f"has no `## {version}` section"
    allowed_tops = [[want], ["unreleased", want]] if stacked else [[want]]
    if any(sections[: len(top)] == top for top in allowed_tops):
        return None
    if stacked:
        return f"top section must be `## {version}` (optionally under one `## Unreleased`), found `## {sections[0]}`"
    return (
        f"top section must be `## {version}`, found `## {sections[0]}` "
        "(a PR into the default branch releases the version: fold any Unreleased notes into it)"
    )


# --- paths ------------------------------------------------------------------

def is_shipped(rel: str) -> bool:
    """Whether a path relative to the plugin directory ships to users."""
    parts = rel.split("/")
    if parts[0] in NOT_SHIPPED_TOP:
        return False
    if any(p in CACHE_DIRS for p in parts):
        return False
    return not rel.endswith(CACHE_SUFFIXES)


def local_plugin_dir(source) -> str | None:
    """`<name>` for a `./plugins/<name>` source, else None."""
    if not isinstance(source, str):
        return None
    prefix = f"./{PLUGINS_DIR}/"
    if not source.startswith(prefix):
        return None
    name = source[len(prefix):].rstrip("/")
    if not name or "/" in name or name in (".", "..") or "\\" in name:
        return None
    return name


# --- git --------------------------------------------------------------------

def git(repo: Path, *args: str, ok_codes=(0,)) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    except OSError as exc:
        raise CannotCheck(f"cannot run git: {exc}") from exc
    if proc.returncode not in ok_codes:
        raise CannotCheck(f"`git {' '.join(args)}` failed: {proc.stderr.strip()}")
    return proc


def resolve_default_branch(repo: Path, given: str | None) -> str:
    if given:
        return given
    proc = git(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{REMOTE}/HEAD", ok_codes=(0, 1, 128))
    head = proc.stdout.strip()
    if proc.returncode == 0 and head.startswith(f"{REMOTE}/"):
        return head[len(REMOTE) + 1:]
    return FALLBACK_DEFAULT_BRANCH


def show(repo: Path, rev: str, path: str) -> str | None:
    """File content at a revision, or None if the path does not exist there."""
    if git(repo, "cat-file", "-e", f"{rev}:{path}", ok_codes=(0, 1, 128)).returncode != 0:
        return None
    return git(repo, "show", f"{rev}:{path}").stdout


def changed_shipped(repo: Path, merge_base: str, name: str) -> list[str]:
    prefix = f"{PLUGINS_DIR}/{name}/"
    out = git(repo, "diff", "--name-only", "--no-renames", "-z", merge_base, "HEAD", "--", prefix).stdout
    return [p for p in out.split("\0") if p.startswith(prefix) and is_shipped(p[len(prefix):])]


# --- check ------------------------------------------------------------------

def read_version(text: str | None):
    """(version or None, error or None) from plugin.json text."""
    if text is None:
        return None, "is missing"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"is not valid JSON ({exc})"
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str):
        return None, "has no string `version`"
    return version, None


def check_plugin(repo: Path, name: str, default_ref: str, merge_base: str, stacked: bool) -> list[str]:
    base = f"{PLUGINS_DIR}/{name}"
    manifest = f"{base}/.claude-plugin/plugin.json"
    errors = []
    version, err = read_version(show(repo, "HEAD", manifest))
    if err:
        return [f"{name}: {manifest} {err}"]
    if parse_semver(version) is None:
        errors.append(f"{name}: version {version!r} in {manifest} is not valid semver (MAJOR.MINOR.PATCH)")

    changed = changed_shipped(repo, merge_base, name)
    if changed and parse_semver(version) is not None:
        old_text = show(repo, default_ref, manifest)
        if old_text is not None:
            old, old_err = read_version(old_text)
            old_key = parse_semver(old) if old_err is None else None
            if old_key is not None and not parse_semver(version) > old_key:
                listed = ", ".join(p[len(base) + 1:] for p in changed[:5]) + (", ..." if len(changed) > 5 else "")
                errors.append(
                    f"{name}: shipped files changed ({listed}) but version {version} is not greater than "
                    f"{default_ref}'s {old}. Bump `version` in {manifest} above {old} and add a "
                    f"`## <new version>` section to {base}/CHANGELOG.md; without a bump "
                    "`claude plugin update` never delivers the change."
                )

    changelog = show(repo, "HEAD", f"{base}/CHANGELOG.md")
    if changelog is None:
        errors.append(f"{name}: {base}/CHANGELOG.md is missing; add one with a `## {version}` section")
    else:
        problem = changelog_problem(changelog, version, stacked)
        if problem:
            errors.append(f"{name}: {base}/CHANGELOG.md {problem}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--default-branch", default=None,
                        help=f"default branch name; empty: {REMOTE}/HEAD, else {FALLBACK_DEFAULT_BRANCH}")
    parser.add_argument("--base-ref", default=None,
                        help="the PR's base branch; empty or absent means a push (judged like a PR into the default branch)")
    args = parser.parse_args(argv)
    repo = Path(args.repo)

    try:
        default_branch = resolve_default_branch(repo, args.default_branch)
        default_ref = f"{REMOTE}/{default_branch}"
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{default_ref}^{{commit}}",
               ok_codes=(0, 1)).returncode != 0:
            raise CannotCheck(f"{default_ref} not found; fetch it first (CI: actions/checkout with fetch-depth: 0)")
        merge_base = git(repo, "merge-base", f"refs/remotes/{default_ref}", "HEAD").stdout.strip()
        marketplace_text = show(repo, "HEAD", ".claude-plugin/marketplace.json")
        if marketplace_text is None:
            raise CannotCheck(".claude-plugin/marketplace.json not found at HEAD")
        try:
            plugins = json.loads(marketplace_text).get("plugins", [])
        except (ValueError, AttributeError) as exc:
            raise CannotCheck(f".claude-plugin/marketplace.json is not a JSON object: {exc}") from exc
        stacked = bool(args.base_ref) and args.base_ref != default_branch
        errors, checked = [], []
        for entry in plugins if isinstance(plugins, list) else []:
            name = local_plugin_dir(entry.get("source")) if isinstance(entry, dict) else None
            if name is None:
                continue
            checked.append(name)
            errors.extend(check_plugin(repo, name, f"refs/remotes/{default_ref}", merge_base, stacked))
    except CannotCheck as exc:
        print(f"version check: cannot check: {exc}", file=sys.stderr)
        return 2

    mode = f"stacked on {args.base_ref}" if stacked else f"into {default_branch}"
    if errors:
        for e in errors:
            print(f"version check: FAIL {e}", file=sys.stderr)
        return 1
    print(f"version check: ok ({mode}; compared with {default_ref}): {', '.join(checked) or 'no local plugins'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
