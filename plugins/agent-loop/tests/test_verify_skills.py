"""The `check` rung: the ladder reads the same everywhere, and verify skills have the shape DESIGN.md gives them."""

import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
LADDER = ["note", "instruction", "check", "hook", "test"]
EXAMPLE = PLUGIN / "docs" / "examples" / "verify-doc-drift" / "SKILL.md"
TEMPLATE = PLUGIN / "skills" / "retro" / "references" / "verify-skill.md"
# The pre-approvals a verify skill may carry: read-only tools, and two exact read-only git commands
# (exact entries cannot absorb an extra flag such as --output=<file>).
ALLOWED = {"Read", "Grep", "Glob", "Bash(git diff --name-only HEAD)", "Bash(git status --porcelain)"}


def ladder_rows(path):
    text = (PLUGIN / path).read_text()
    section = text.split("## The promotion ladder", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `([a-z]+)` \|", section, re.M)


@pytest.mark.parametrize("path", ["docs/DESIGN.md", "README.md"])
def test_ladder_tables_list_every_rung_in_order(path):
    assert ladder_rows(path) == LADDER


def test_ledger_example_lists_every_rung():
    text = (PLUGIN / "docs/DESIGN.md").read_text()
    (comment,) = re.findall(r"rung: \w+ +# (.*)$", text, re.M)
    assert comment.split(" | ") == LADDER


def test_manifest_descriptions_name_the_check_rung():
    for path in [PLUGIN / ".claude-plugin/plugin.json", PLUGIN.parent.parent / ".claude-plugin/marketplace.json"]:
        text = path.read_text()
        assert "(instruction, check, hook, test)" in text, path
        json.loads(text)


def frontmatter(text):
    m = re.search(r"^---\n(.*?)\n---\n", text, re.S | re.M)
    assert m, "no frontmatter"
    fm, key = {}, None
    for line in m.group(1).splitlines():
        if line.startswith("  - "):
            fm[key].append(line[4:].strip())
        else:
            key, _, val = line.partition(":")
            fm[key] = val.strip() or []
    return fm, text[m.end():]


def template_text():
    # The retro's template is the first fenced markdown block in its reference.
    return TEMPLATE.read_text().split("```markdown\n", 1)[1].split("\n```\n", 1)[0] + "\n"


@pytest.mark.parametrize("source", ["example", "template"])
def test_verify_skill_shape(source):
    text = EXAMPLE.read_text() if source == "example" else template_text()
    fm, body = frontmatter(text)
    assert fm["name"].startswith("verify-")
    if source == "example":
        assert fm["name"] == EXAMPLE.parent.name
    assert "Use when" in fm["description"]
    assert set(fm["allowed-tools"]) <= ALLOWED, fm["allowed-tools"]
    assert not any(re.search(r"Write|Edit|\*", t) for t in fm["allowed-tools"])
    assert "PASS" in body and "FAIL" in body and "file:line" in body.replace("path:line", "file:line")
    assert not re.search(r"(?im)^#+ .*\bfix", body), "a verify skill reports; it never fixes"


def test_example_is_not_a_plugin_skill():
    # Plugin skills are discovered under skills/; the example must stay outside it.
    assert not [p for p in (PLUGIN / "skills").rglob("verify-*") if p.is_dir()]
    assert "skills" not in EXAMPLE.relative_to(PLUGIN).parts
