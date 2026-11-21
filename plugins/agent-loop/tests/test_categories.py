"""The category catalog is the shared vocabulary: every category a shipped doc names must be in it."""

import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
CATALOG = PLUGIN / "docs" / "categories.md"
NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"

# Places a shipped doc names a category: a record's `category:` field, a parenthesised
# `(name)` tag, "category `name`", "Report as `name`", an "e.g." example, a table cell
# in a category column, and a "`name`, not ..." naming example.
CONTEXTS = [
    rf"category:\s*`?({NAME})",
    rf"\(`({NAME})`\)",
    rf"category `({NAME})`",
    rf"Report as `({NAME})`",
    rf"e\.g\. `?({NAME})",
    rf"\| `({NAME})` \|",
    rf"`({NAME})`, not",
]


def catalog(text=None):
    text = CATALOG.read_text() if text is None else text
    return re.findall(rf"^\| `({NAME})` \|", text, re.M)


def shipped_docs():
    skip = {".venv", ".pytest_cache", "tests"}
    return sorted(p for p in PLUGIN.rglob("*.md") if not skip & set(p.relative_to(PLUGIN).parts))


def named_categories(text):
    found = set()
    for pat in CONTEXTS:
        found |= set(re.findall(pat, text))
    return found


def test_catalog_names_are_unique_and_cover_the_starter_set():
    names = catalog()
    assert len(names) == len(set(names))
    assert {"skipped-plan-approval", "skipped-independent-review", "branch-over-budget", "stale-trunk",
            "scope-mismatch", "generated-artifact-not-regenerated", "new-file-matches-generator-glob",
            "generated-file-hand-edit", "measurement-attribution-leak", "shared-state-false-failures",
            "wrong-auth-identity", "shell-portability", "leftover-resources", "redaction-gap",
            "over-broad-pre-approval", "regex-performance", "contract-gap", "contract-self-contradiction",
            "doc-drift"} <= set(names)


def test_the_scan_covers_the_docs_that_name_categories():
    docs = {str(p.relative_to(PLUGIN)) for p in shipped_docs()}
    assert {"README.md", "docs/DESIGN.md", "docs/categories.md", "agents/reviewer.md", "agents/tester.md",
            "skills/lead/SKILL.md", "skills/lead/references/run-record.md", "skills/retro/SKILL.md"} <= docs


@pytest.mark.parametrize("doc", [str(p.relative_to(PLUGIN)) for p in shipped_docs()])
def test_every_category_a_shipped_doc_names_is_in_the_catalog(doc):
    unknown = named_categories((PLUGIN / doc).read_text()) - set(catalog())
    assert not unknown, f"{doc} names categories missing from docs/categories.md: {sorted(unknown)}"


def test_removing_a_catalog_row_is_caught():
    # The check must fail when a category the docs use loses its catalog row.
    text = CATALOG.read_text()
    used = set().union(*(named_categories(p.read_text()) for p in shipped_docs() if p != CATALOG))
    for name in sorted(used):
        without = "\n".join(l for l in text.splitlines() if not l.startswith(f"| `{name}` |"))
        assert name not in catalog(without)
    assert "over-broad-pre-approval" in used and "doc-drift" in used


def test_design_measurement_invariants_use_catalog_names():
    text = (PLUGIN / "docs/DESIGN.md").read_text()
    section = text.split("## Measurement invariants", 1)[1].split("\n## ", 1)[0]
    used = set(re.findall(rf"\| `({NAME})` \|$", section, re.M))
    assert {"measurement-attribution-leak", "shared-state-false-failures", "wrong-auth-identity",
            "silent-allowlist", "leftover-resources", "shell-portability", "new-check-not-opt-in"} == used
    assert used <= set(catalog())


@pytest.mark.parametrize("path", [str(p.relative_to(PLUGIN)) for p in shipped_docs()]
                         + [str(p.relative_to(PLUGIN)) for p in sorted((PLUGIN / "scripts").glob("*.py"))])
def test_shipped_files_do_not_cite_issue_numbers(path):
    # Installed users do not have this repository's issues; describe planned work in words.
    text = (PLUGIN / path).read_text()
    assert not re.search(r"(?<![\w&/])#\d+\b", text), path
