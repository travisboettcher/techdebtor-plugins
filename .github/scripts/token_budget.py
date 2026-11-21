#!/usr/bin/env python3
"""Fail when a plugin's always-on token cost exceeds its ceiling.

Usage: python3 token_budget.py [--root .] [--budgets .github/token-budgets.json]
                               [--claude "npx -y @anthropic-ai/claude-code@<version>"]

For every plugin in .claude-plugin/marketplace.json, runs
`<claude> --plugin-dir <source> plugin details -- <name>`, reads the
"Always-on: ~N tok" line and compares N with the plugin's ceiling in the
budgets file ({"always_on_tokens": {"<name>": <ceiling>}}). A plugin whose
directory is not on this branch, or whose source is not a local path, is
skipped with a notice. The CLI runs signed out in a fresh home directory, so
a local run measures what CI measures. Exit 0 when every plugin is within its ceiling, 1 when
one is over, has no ceiling, or cannot be measured, 2 when the budgets file
or marketplace cannot be read. Standard library only; parsing is linear in
the size of the CLI's output.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
GROUPED = re.compile(r"\d{1,3}(?:,\d{3})*")
DECIMAL = re.compile(r"\d+(?:\.\d+)?")
TIMEOUT = 300
# Credentials change the CLI's estimate (a signed-in CLI reports more than CI's signed-out one), so
# the CLI always runs signed out, in a fresh home, locally as in CI.
CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


def parse_always_on(text):
    """Return the always-on token count from `claude plugin details` output, or raise ValueError."""
    found = []
    for line in ANSI.sub("", text).splitlines():
        line = line.strip()
        if not line.startswith("Always-on:"):
            continue
        words = line[len("Always-on:"):].split()
        if len(words) < 2 or words[1] != "tok":
            raise ValueError(f"unexpected always-on line: {line[:200]!r}")
        number = words[0].removeprefix("~")
        scale = 1
        if number.endswith("k"):
            number, scale = number[:-1], 1000
        if scale == 1 and GROUPED.fullmatch(number):
            found.append(int(number.replace(",", "")))
        elif DECIMAL.fullmatch(number):
            found.append(round(float(number) * scale))
        else:
            raise ValueError(f"unexpected always-on cost: {words[0][:200]!r}")
    if len(found) != 1:
        raise ValueError(f"expected one always-on line, found {len(found)}")
    return found[0]


def signed_out_env(home):
    env = {k: v for k, v in os.environ.items() if k not in CREDENTIALS}
    env.update(HOME=home, CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"))
    return env


def escape(text):
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotate(level, message):
    print(f"::{level} title=token budget::{escape(message)}")


def load_budgets(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    budgets = data.get("always_on_tokens") if isinstance(data, dict) else None
    if not isinstance(budgets, dict):
        raise ValueError("expected an object with an \"always_on_tokens\" object")
    for name, ceiling in budgets.items():
        if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 0:
            raise ValueError(f"the ceiling for {name!r} is not a whole number of tokens")
    return budgets


def load_plugins(root):
    data = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list) or not all(isinstance(p, dict) and isinstance(p.get("name"), str)
                                                for p in plugins):
        raise ValueError("marketplace.json has no list of named plugins")
    return plugins


def check_plugin(root, plugin, budgets, claude):
    """Return True when the plugin is within its ceiling or skipped, False otherwise."""
    name, source = plugin["name"], plugin.get("source")
    if not isinstance(source, str) or not source.startswith("./"):
        annotate("notice", f"{name}: source is not a local path; skipped")
        return True
    directory = (root / source).resolve()
    if not directory.is_relative_to(root.resolve()):
        annotate("error", f"{name}: source {source} is outside the repository")
        return False
    if not directory.is_dir():
        annotate("notice", f"{name}: {source.removeprefix('./')} is not on this branch; skipped")
        return True
    if name not in budgets:
        annotate("error", f"{name} has no ceiling: add it to the budgets file")
        return False
    # "--" ends the options: a name from the marketplace is never read as one.
    argv = claude + ["--plugin-dir", str(directory), "plugin", "details", "--", name]
    try:
        with tempfile.TemporaryDirectory(prefix="token-budget-") as home:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, cwd=root,
                                  env=signed_out_env(home))
    except (OSError, subprocess.TimeoutExpired) as e:
        annotate("error", f"{name}: could not run `plugin details`: {e}")
        return False
    if proc.returncode != 0:
        annotate("error", f"{name}: `plugin details` exited {proc.returncode}: {(proc.stderr or proc.stdout)[-500:]}")
        return False
    try:
        cost = parse_always_on(proc.stdout)
    except ValueError as e:
        annotate("error", f"{name}: could not read the always-on cost: {e}")
        return False
    ceiling = budgets[name]
    if cost > ceiling:
        annotate("error", f"{name}: always-on ~{cost} tok exceeds its ceiling {ceiling}; "
                          "cut the descriptions, or raise the ceiling in the budgets file with a reason in the PR")
        return False
    print(f"{name}: always-on ~{cost} tok, ceiling {ceiling}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--budgets", default=".github/token-budgets.json")
    ap.add_argument("--claude", default="claude", help="the command that runs the Claude Code CLI")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        budgets = load_budgets(args.budgets)
        plugins = load_plugins(root)
    except (OSError, ValueError) as e:
        annotate("error", f"cannot read the budgets or the marketplace: {e}")
        return 2
    claude = shlex.split(args.claude)
    results = [check_plugin(root, p, budgets, claude) for p in plugins]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
