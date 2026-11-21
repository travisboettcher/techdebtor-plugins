"""Keep the docs, the skill and the scanner consistent with each other."""

import json
import re
from pathlib import Path

import agent_ready_scan as ars

PLUGIN = Path(__file__).resolve().parent.parent
RUBRIC = (PLUGIN / "docs" / "RUBRIC.md").read_text()
SKILL = (PLUGIN / "skills" / "audit" / "SKILL.md").read_text()
README = (PLUGIN / "README.md").read_text()
CHANGELOG = (PLUGIN / "CHANGELOG.md").read_text()
MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())


def _frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m
    return m.group(1)


def _allowed_tools(text):
    fm = _frontmatter(text)
    block = fm.split("allowed-tools:", 1)[1]
    return [line.strip()[2:] for line in block.splitlines() if line.strip().startswith("- ")]


def test_every_check_and_tool_kind_is_documented():
    kinds = set(ars.CHECK_KEYWORDS)
    kinds |= {k for _t, k, _g in ars.FILE_TOOLS}
    kinds |= {k for _t, k, _r, _g in ars.CONTENT_MARKERS}
    missing = sorted(k for k in kinds if f"`{k}`" not in RUBRIC)
    assert not missing, missing


def test_every_ci_capability_is_in_the_rubric_table():
    for cap in ars.CAPABILITY_MARKERS:
        assert f"| `{cap}` |" in RUBRIC, cap


def test_scanner_top_level_keys_are_documented(tmp_path):
    keys = set(ars.scan(tmp_path))
    keys -= {"schema", "root"}
    for key in keys:
        assert f"`{key}`" in SKILL, f"SKILL.md does not list {key}"
        assert f"``{key}``" in ars.__doc__, f"scanner docstring does not list {key}"


def test_rubric_json_example_parses_and_uses_documented_enums():
    block = RUBRIC.split("```json\n", 1)[1].split("\n```", 1)[0]
    data = json.loads(block)
    layer_list = RUBRIC.split("- `layer` is one of ", 1)[1].split("\n", 1)[0]
    layers = set(re.findall(r"`([a-z_]+)`", layer_list))
    assert {entry["layer"] for entry in data["layers"]} <= layers
    assert {f["layer"] for f in data["fixes"]} <= layers
    assert {c["capability"] for c in data["ci_capabilities"]} <= set(ars.CAPABILITY_MARKERS)
    assert len(layers) == 17


def test_skill_pre_approvals_are_read_only_and_exact():
    tools = _allowed_tools(SKILL)
    assert tools[:3] == ["Read", "Glob", "Grep"]
    for tool in tools[3:]:
        assert tool.startswith("Bash(git ") and tool.endswith(")"), tool
        assert "*" not in tool, f"wildcard pre-approval: {tool}"
    assert not any("python" in t or "agent_ready_scan" in t or "gh " in t for t in tools)
    assert not any(t in ("Write", "Edit", "Bash", "WebFetch") for t in tools)


def test_commands_are_namespaced():
    for text in (SKILL, README, RUBRIC):
        assert not re.search(r"(?<![\w:-])/audit\b", text)
    assert "/agent-ready:audit" in README and "/agent-ready:audit" in SKILL


def test_skill_calls_the_bundled_scanner_isolated():
    assert 'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/agent_ready_scan.py"' in SKILL
    assert (PLUGIN / "scripts" / "agent_ready_scan.py").exists()


def test_readme_limits_match_the_code():
    assert f"{ars.DEFAULT_MAX_FILES:,}" in README
    assert f"{ars.DEFAULT_MAX_BYTES // 1024} KB" in README


def test_version_is_in_the_changelog():
    assert CHANGELOG.split("\n## ", 1)[1].startswith(MANIFEST["version"])
    assert MANIFEST["name"] == "agent-ready"
