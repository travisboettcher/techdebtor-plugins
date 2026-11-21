#!/usr/bin/env python3
"""Lint skill, agent and command front matter as prompt text.

Vale never lints YAML front matter, but `description` (and `argument-hint`) in a
skill's, agent's or command's front matter is model-facing text loaded into
every session. This script copies those values into Markdown files that Vale
lints with the Prompt style, then maps Vale's alerts back to the source.

  frontmatter_prose.py extract [--root .] --out DIR
      Writes DIR/<source dir>/<stem>.<key>.md for each value of
      plugins/*/skills/**/SKILL.md, plugins/*/agents/**/*.md and
      plugins/*/commands/**/*.md, and DIR/frontmatter-map.json.
  frontmatter_prose.py remap --out DIR VALE_JSON
      Prints VALE_JSON (Vale's JSON, run from DIR with relative paths) with
      each alert moved to its source file, line and column.

Only top-level `key: value` lines are read: a plain, single- or double-quoted
or block scalar, with any indented continuation lines. Exit 0 on success, 2
when the map or Vale's output does not fit. Standard library only; every step
is linear in the size of the input.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

KEYS = ("description", "argument-hint")
GLOBS = ("plugins/*/skills/**/SKILL.md", "plugins/*/agents/**/*.md", "plugins/*/commands/**/*.md")
MAP = "frontmatter-map.json"


@dataclass
class Field:
    key: str
    lines: list = field(default_factory=list)  # (source line, source column, text), 1-based


def _front_matter(text):
    """Return [(line number, line)] between the opening and closing `---`, or [] if there is none."""
    lines = text.removeprefix("﻿").split("\n")
    if lines[0].rstrip("\r") != "---":
        return []
    body = []
    for number, line in enumerate(lines[1:], start=2):
        line = line.rstrip("\r")
        if line == "---":
            return body
        body.append((number, line))
    return []


def prose_fields(text):
    """Return a Field for each top-level description or argument-hint with any text."""
    found, current, quote = [], None, ""
    for number, line in _front_matter(text):
        if line[:1] in (" ", "\t") or not line.strip():
            if current is not None and line.strip():
                stripped = line.lstrip(" \t")
                value = stripped.rstrip()
                if quote and value.endswith(quote):
                    value = value[:-1].rstrip()
                if value:
                    current.lines.append((number, len(line) - len(stripped) + 1, value))
            continue
        current, quote = None, ""
        key, sep, rest = line.partition(":")
        if not sep or key not in KEYS:
            continue
        current = Field(key)
        found.append(current)
        start = len(key) + 1 + (len(rest) - len(rest.lstrip(" \t")))
        value = rest.strip()
        if value[:1] in ("|", ">"):
            continue  # a block scalar: the text is on the indented lines below
        if value[:1] in ('"', "'"):
            quote, value, start = value[0], value[1:], start + 1
            if value.endswith(quote):
                value, quote = value[:-1], ""
        if value:
            current.lines.append((number, start + 1, value))
    return [f for f in found if f.lines]


def extract(root, out):
    mapping = {}
    sources = sorted({p for g in GLOBS for p in root.glob(g) if p.is_file() and not p.is_symlink()})
    for source in sources:
        rel = source.relative_to(root)
        for f in prose_fields(source.read_text(encoding="utf-8", errors="replace")):
            target = rel.parent / f"{rel.stem}.{f.key}.md"
            (out / target.parent).mkdir(parents=True, exist_ok=True)
            (out / target).write_text("".join(text + "\n" for _, _, text in f.lines), encoding="utf-8")
            mapping[target.as_posix()] = {"source": rel.as_posix(), "lines": [[n, c] for n, c, _ in f.lines]}
    out.mkdir(parents=True, exist_ok=True)
    (out / MAP).write_text(json.dumps(mapping, indent=1, sort_keys=True), encoding="utf-8")
    print(f"frontmatter_prose: {len(mapping)} values from {len(sources)} files", file=sys.stderr)
    return 0


def remap(out, vale_json):
    mapping = json.loads((out / MAP).read_text(encoding="utf-8"))
    results = json.loads(Path(vale_json).read_text(encoding="utf-8"))
    if not isinstance(results, dict):
        raise ValueError("Vale's output is not a JSON object")
    if "Code" in results and "Text" in results:
        return results  # Vale's own error: pass it on for vale_annotations.py
    remapped = {}
    for path, alerts in results.items():
        entry = mapping.get(path.removeprefix("./"))
        if entry is None or not isinstance(alerts, list):
            raise ValueError(f"{path!r} is not a file extract wrote")
        for alert in alerts:
            line = alert.get("Line") if isinstance(alert, dict) else None
            if not isinstance(line, int) or not 1 <= line <= len(entry["lines"]):
                raise ValueError(f"an alert in {path!r} has no line extract wrote")
            source_line, column = entry["lines"][line - 1]
            moved = dict(alert, Line=source_line)
            span = alert.get("Span")
            if isinstance(span, list) and all(isinstance(s, int) for s in span):
                moved["Span"] = [s + column - 1 for s in span]
            remapped.setdefault(entry["source"], []).append(moved)
    return remapped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--root", default=".")
    ex.add_argument("--out", required=True)
    rm = sub.add_parser("remap")
    rm.add_argument("--out", required=True)
    rm.add_argument("vale_json")
    args = ap.parse_args(argv)
    if args.command == "extract":
        return extract(Path(args.root), Path(args.out))
    try:
        print(json.dumps(remap(Path(args.out), args.vale_json), indent=1))
    except (OSError, ValueError, RecursionError, KeyError, TypeError) as e:
        print(f"frontmatter_prose: cannot remap: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
