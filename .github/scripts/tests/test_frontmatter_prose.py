"""frontmatter_prose.py lints skill and agent front matter (description, argument-hint) as prompts."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import frontmatter_prose as fp  # noqa: E402


def fields(text):
    return [(f.key, f.lines) for f in fp.prose_fields(text)]


def test_double_quoted_single_line_keeps_the_column():
    text = '---\nname: x\ndescription: "Please try it."\n---\nbody\n'
    assert fields(text) == [("description", [(3, 15, "Please try it.")])]


def test_single_quoted_plain_and_argument_hint():
    text = "---\ndescription: 'It''s fine'\nargument-hint: <task description>\nname: y\n---\n"
    assert fields(text) == [("description", [(2, 15, "It''s fine")]),
                            ("argument-hint", [(3, 16, "<task description>")])]


def test_plain_value_with_indented_continuation_lines():
    text = "---\ndescription: first line\n  second line\n\n  third\nname: z\n---\n"
    assert fields(text) == [("description", [(2, 14, "first line"), (3, 3, "second line"), (5, 3, "third")])]


def test_block_scalar():
    text = "---\ndescription: >-\n    Folded text\n    goes on.\ntools: [Read]\n---\n"
    assert fields(text) == [("description", [(3, 5, "Folded text"), (4, 5, "goes on.")])]


def test_quoted_value_spanning_lines_drops_the_closing_quote():
    text = '---\ndescription: "starts here\n  and ends here."\n---\n'
    assert fields(text) == [("description", [(2, 15, "starts here"), (3, 3, "and ends here.")])]


@pytest.mark.parametrize("text", ["no front matter\ndescription: x\n", "---\ndescription: x\n",
                                  "body\n---\ndescription: x\n---\n", "", "---\n---\n"])
def test_no_or_unterminated_front_matter_yields_nothing(text):
    assert fields(text) == []


def test_nested_and_other_keys_are_ignored():
    text = "---\nname: n\nmeta:\n  description: nested\ndescriptions: no\n---\ndescription: body\n"
    assert fields(text) == []


def test_crlf_and_bom():
    text = '﻿---\r\ndescription: "Hi there."\r\n---\r\n'
    assert fields(text) == [("description", [(2, 15, "Hi there.")])]


def test_parsing_is_linear_time():
    text = "---\ndescription: " + "a " * 300_000 + "\n" + "  b\n" * 100_000 + "---\n"
    start = time.perf_counter()
    assert len(fp.prose_fields(text)[0].lines) == 100_001
    assert time.perf_counter() - start < 2


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "plugins/p/skills/s").mkdir(parents=True)
    (root / "plugins/p/agents/nested").mkdir(parents=True)
    (root / "plugins/p/commands").mkdir(parents=True)
    (root / "plugins/p/docs").mkdir(parents=True)
    (root / "plugins/p/skills/s/SKILL.md").write_text('---\nname: s\ndescription: "Skill text."\nargument-hint: <x>\n---\n')
    (root / "plugins/p/skills/s/references").mkdir()
    (root / "plugins/p/skills/s/references/r.md").write_text("---\ndescription: not a skill\n---\n")
    (root / "plugins/p/agents/a.md").write_text("---\ndescription: Agent text.\n---\n")
    (root / "plugins/p/agents/nested/b.md").write_text("---\ndescription: Nested.\n---\n")
    (root / "plugins/p/commands/c.md").write_text("---\ndescription: Command.\n---\n")
    (root / "plugins/p/docs/d.md").write_text("---\ndescription: Docs are not prompts.\n---\n")
    return root


def test_extract_mirrors_paths_under_the_prompt_globs(repo, tmp_path):
    out = tmp_path / "out"
    assert fp.main(["extract", "--root", str(repo), "--out", str(out)]) == 0
    written = sorted(str(p.relative_to(out)) for p in out.rglob("*.md"))
    assert written == ["plugins/p/agents/a.description.md", "plugins/p/agents/nested/b.description.md",
                       "plugins/p/commands/c.description.md", "plugins/p/skills/s/SKILL.argument-hint.md",
                       "plugins/p/skills/s/SKILL.description.md"]
    assert (out / "plugins/p/skills/s/SKILL.description.md").read_text() == "Skill text.\n"
    mapping = json.loads((out / fp.MAP).read_text())
    assert mapping["plugins/p/skills/s/SKILL.description.md"] == {
        "source": "plugins/p/skills/s/SKILL.md", "lines": [[3, 15]]}


def test_extract_skips_symlinks(repo, tmp_path):
    (repo / "plugins/p/agents/link.md").symlink_to(repo / "plugins/p/agents/a.md")
    out = tmp_path / "out"
    fp.main(["extract", "--root", str(repo), "--out", str(out)])
    assert not (out / "plugins/p/agents/link.description.md").exists()


def test_remap_points_alerts_at_the_source_line_and_column(repo, tmp_path, capsys):
    out = tmp_path / "out"
    fp.main(["extract", "--root", str(repo), "--out", str(out)])
    vale = tmp_path / "fm.json"
    vale.write_text(json.dumps({"plugins/p/skills/s/SKILL.description.md": [
        {"Check": "Prompt.Politeness", "Severity": "error", "Line": 1, "Span": [1, 5], "Message": "m"}]}))
    capsys.readouterr()
    assert fp.main(["remap", "--out", str(out), str(vale)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"plugins/p/skills/s/SKILL.md": [
        {"Check": "Prompt.Politeness", "Severity": "error", "Line": 3, "Span": [15, 19], "Message": "m"}]}


def test_remap_passes_a_vale_error_through(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / fp.MAP).write_text("{}")
    vale = tmp_path / "fm.json"
    vale.write_text(json.dumps({"Code": "E201", "Text": "bad"}))
    assert fp.main(["remap", "--out", str(out), str(vale)]) == 0
    assert json.loads(capsys.readouterr().out) == {"Code": "E201", "Text": "bad"}


def test_remap_rejects_unknown_files_and_lines(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / fp.MAP).write_text(json.dumps({"a.description.md": {"source": "a.md", "lines": [[2, 14]]}}))
    vale = tmp_path / "fm.json"
    for data in ({"b.md": []}, {"a.description.md": [{"Line": 5, "Span": [1, 2]}]}):
        vale.write_text(json.dumps(data))
        assert fp.main(["remap", "--out", str(out), str(vale)]) == 2
