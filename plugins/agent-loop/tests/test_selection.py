"""The selection table (docs/selection.yml), a project's override of it, and the miner's per-specialist report."""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from retro_mine import (DEFAULT_SELECTION, OVERRIDE_SELECTION, ledger_report, load_ledger, load_selection,
                        merge_selection, parse_yaml_lite, specialist_report)

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "retro_mine.py"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"


def default():
    return parse_yaml_lite(DEFAULT_SELECTION.read_text())


# --- the default table ------------------------------------------------------------

def test_default_table_is_where_the_docs_say():
    assert DEFAULT_SELECTION == PLUGIN / "docs" / "selection.yml"
    assert OVERRIDE_SELECTION == Path(".claude") / "agent-loop" / "selection.yml"


def test_default_table_is_consistent():
    t = default()
    specs = t["specialists"]
    assert t["baseline"] == ["test-runner", "correctness-reviewer"]
    for name, s in specs.items():
        assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*", name) and not name.startswith("verify-"), name
        assert s["pool"] in ("tester", "reviewer"), name
        assert s["weight"] in ("light", "heavy"), name
        assert isinstance(s["categories"], list), name
    for name in t["baseline"]:
        assert not specs[name].get("opt_in"), "the baseline is never opt-in"
    for tag, row in t["tags"].items():
        assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*", tag)
        assert row["when"] and set(row["run"]) <= set(specs), tag
    assert {"untrusted-input", "permissions", "data-migration", "public-api", "concurrency", "perf-sensitive",
            "ui", "test-infra", "security-sensitive"} <= set(t["tags"])
    assert set(t["budget"]) == {"heavy_runs", "heavy_minutes"}
    # Every specialist is reachable: the baseline, a tag, or (check-runner) the plan's verify skills.
    reachable = set(t["baseline"]) | {s for row in t["tags"].values() for s in row["run"]} | {"check-runner"}
    assert reachable == set(specs)


def test_the_moved_standing_checks_keep_their_triggers():
    # The tester's regex timing and the reviewer's least-privilege check moved into specialists;
    # the tags that used to trigger them must still select them, and never as opt-in.
    t = default()
    assert "fuzzer" in t["tags"]["regex"]["run"] and "fuzzer" in t["tags"]["untrusted-input"]["run"]
    assert "permissions-reviewer" in t["tags"]["permissions"]["run"]
    assert "measurement-auditor" in t["tags"]["test-infra"]["run"]
    for name in ("fuzzer", "permissions-reviewer", "measurement-auditor", "check-runner"):
        assert not t["specialists"][name].get("opt_in"), name


def test_new_heavy_specialists_start_opt_in():
    specs = default()["specialists"]
    for name in ("mutation-tester", "api-fuzzer", "system-tester", "perf-tester", "security-scanner"):
        assert specs[name]["opt_in"] is True and specs[name]["weight"] == "heavy", name


def test_every_specialist_category_is_in_the_catalog():
    catalog = set(re.findall(rf"^\| `({NAME})` \|", (PLUGIN / "docs/categories.md").read_text(), re.M))
    used = {c for s in default()["specialists"].values() for c in s["categories"]}
    assert used and used <= catalog, sorted(used - catalog)


def test_design_tag_table_matches_the_data_file():
    # DESIGN.md shows the default table; it must say what docs/selection.yml says.
    text = (PLUGIN / "docs/DESIGN.md").read_text()
    section = text.split("### The selection table", 1)[1].split("\n### ", 1)[0]
    rows = re.findall(r"^\| `([a-z-]+)` \| [^|]+ \| ([^|]+) \|$", section, re.M)
    shown = {tag: re.findall(r"`([a-z-]+)`", run) for tag, run in rows}
    assert shown == {tag: row["run"] for tag, row in default()["tags"].items()}


# --- a project's override ---------------------------------------------------------

def test_no_override_is_the_default():
    table, errors = merge_selection(default(), None)
    assert errors == [] and table == {**default(), "enable": [], "blocking": []}


def test_override_replaces_a_tag_row_adds_tags_and_budget():
    over = parse_yaml_lite("""\
schema: 1
enable: [mutation-tester]
blocking: [mutation-tester]
budget:
  heavy_runs: 2
tags:
  data-migration:
    run: [system-tester]
  sql-migrations:
    when: "Adds a file under migrations/."
    run: [system-tester, api-reviewer]
""")
    table, errors = merge_selection(default(), over)
    assert errors == []
    assert table["tags"]["data-migration"]["run"] == ["system-tester"]
    assert table["tags"]["data-migration"]["when"] == default()["tags"]["data-migration"]["when"]
    assert table["tags"]["sql-migrations"]["run"] == ["system-tester", "api-reviewer"]
    assert table["budget"] == {"heavy_runs": 2, "heavy_minutes": 60}
    assert table["enable"] == ["mutation-tester"] and table["blocking"] == ["mutation-tester"]
    assert table["tags"]["permissions"] == default()["tags"]["permissions"]  # untouched rows stay


@pytest.mark.parametrize("override, complaint", [
    ("baseline: [test-runner]\n", "baseline"),
    ("tags:\n  regex:\n    run: [no-such-agent]\n", "no-such-agent"),
    ("enable: [no-such-agent]\n", "no-such-agent"),
    ("blocking: [fuzzer]\n", "fuzzer"),                       # blocking only applies to enabled opt-in ones
    ("tags:\n  brand-new:\n    run: [fuzzer]\n", "brand-new"),  # a new tag needs `when`
    ("budget:\n  heavy_runs: lots\n", "heavy_runs"),
    ("specialists:\n  fuzzer:\n    weight: light\n", "specialists"),
])
def test_bad_overrides_are_reported_and_ignored(override, complaint):
    table, errors = merge_selection(default(), parse_yaml_lite("schema: 1\n" + override))
    assert errors and any(complaint in e for e in errors), errors
    assert table["baseline"] == default()["baseline"]
    assert table["specialists"] == default()["specialists"]
    assert "no-such-agent" not in json.dumps(table["tags"]) and "no-such-agent" not in table["enable"]
    assert "brand-new" not in table["tags"]
    assert table["budget"]["heavy_runs"] == 6
    assert "fuzzer" not in table["blocking"]


def test_an_override_that_is_not_a_mapping_is_an_error():
    table, errors = merge_selection(default(), ["x"])
    assert errors and table["tags"] == default()["tags"]


def test_load_selection_reads_the_project_override(tmp_path):
    p = tmp_path / OVERRIDE_SELECTION
    p.parent.mkdir(parents=True)
    p.write_text("schema: 1\nenable: [perf-tester]\n")
    sel = load_selection(tmp_path)
    assert sel["override"] == str(OVERRIDE_SELECTION) and sel["errors"] == []
    assert sel["table"]["enable"] == ["perf-tester"]


def test_load_selection_without_override_and_with_a_broken_one(tmp_path):
    sel = load_selection(tmp_path)
    assert sel["override"] is None and sel["errors"] == []
    p = tmp_path / OVERRIDE_SELECTION
    p.parent.mkdir(parents=True)
    p.write_text("tags: [unterminated\n")
    sel = load_selection(tmp_path)
    assert sel["errors"] and sel["table"]["tags"] == default()["tags"]


# --- per-specialist precision and miss rate ---------------------------------------

def _rec(tags, chosen, findings=(), rejected=(), date="2026-11-20"):
    return {"date": date, "plan": {"units": ["u"], "tags": [{"unit": "u", "tags": list(tags)}]},
            "selection": [{"pool": "tester", "round": 1, "chosen": list(chosen)}],
            "findings": list(findings), "rejected": list(rejected)}


def _f(category, specialist=None, caught_by="tester"):
    f = {"stage": "implement", "category": category, "severity": "major", "caught_by": caught_by}
    if specialist is not None:
        f["specialist"] = specialist
    return f


def test_precision_counts_findings_against_rejections():
    recs = [_rec(["regex"], ["test-runner", "fuzzer"],
                 findings=[_f("regex-performance", "fuzzer"), _f("unhandled-input", "fuzzer")],
                 rejected=[{"stage": "test", "category": "unhandled-input", "specialist": "fuzzer", "reason": "r"}])]
    s = specialist_report(recs, default())["by_specialist"]["fuzzer"]
    assert (s["runs"], s["findings"], s["rejected"]) == (1, 2, 1)
    assert s["precision"] == pytest.approx(0.67, abs=0.01)


def test_a_miss_is_a_finding_in_a_chosen_specialists_category_that_it_did_not_report():
    recs = [_rec(["regex"], ["test-runner", "fuzzer"],
                 findings=[_f("regex-performance", caught_by="human"),          # escaped to the human
                           _f("regex-performance", "fuzzer"),                   # caught
                           _f("doc-drift", caught_by="human")])]                # not the fuzzer's category
    s = specialist_report(recs, default())["by_specialist"]["fuzzer"]
    assert (s["findings"], s["misses"]) == (1, 1)
    assert s["miss_rate"] == pytest.approx(0.5)
    assert s["by_tag"]["regex"] == {"runs": 1, "findings": 1, "rejected": 0, "misses": 1}


def test_a_specialist_not_chosen_has_no_misses():
    recs = [_rec([], ["test-runner"], findings=[_f("regex-performance", caught_by="ci")])]
    rep = specialist_report(recs, default())
    assert "fuzzer" not in rep["by_specialist"]
    assert rep["by_specialist"]["test-runner"]["misses"] == 0


def test_merged_findings_credit_every_specialist_that_reported_them():
    recs = [_rec(["untrusted-input"], ["fuzzer"], findings=[_f("unhandled-input", ["fuzzer", "security-reviewer"])])]
    recs[0]["selection"].append({"pool": "reviewer", "round": 1, "chosen": ["correctness-reviewer", "security-reviewer"]})
    rep = specialist_report(recs, default())["by_specialist"]
    assert rep["fuzzer"]["findings"] == 1 and rep["security-reviewer"]["findings"] == 1
    assert rep["security-reviewer"]["misses"] == 0


def test_tags_report_runs_and_escapes():
    recs = [_rec(["public-api"], ["test-runner"], findings=[_f("breaking-change", caught_by="human"),
                                                            _f("logic-error", "test-runner")]),
            _rec(["public-api", "ui"], ["test-runner"], findings=[_f("breaking-change", caught_by="ci")])]
    tags = specialist_report(recs, default())["by_tag"]
    assert tags["public-api"] == {"runs": 2, "escaped": {"breaking-change": 2}}
    assert tags["ui"] == {"runs": 1, "escaped": {"breaking-change": 1}}


def test_records_without_a_selection_are_skipped_and_odd_shapes_do_not_crash():
    recs = [{"date": "2026-11-01", "findings": [_f("regex-performance", caught_by="human")]},  # before the swarm
            {"date": "2026-11-02", "plan": ".claude/runs/x.plan.md", "selection": [{"chosen": ["fuzzer"]}],
             "findings": None},
            {"date": "2026-11-03", "plan": {"tags": "nope"}, "selection": "nope"},
            {"date": "2026-11-04", "selection": [{"chosen": "fuzzer"}, None, {"chosen": [None, 3]}],
             "findings": [_f("regex-performance", specialist=7)]}]
    rep = specialist_report(recs, default())
    assert rep["records"] == 2
    assert rep["by_specialist"]["fuzzer"]["runs"] == 2


def test_diff_derived_tags_in_a_selection_entry_count():
    rec = _rec([], ["measurement-auditor"])
    rec["selection"][0]["tags"] = ["test-infra"]
    rep = specialist_report([rec], default())
    assert rep["by_specialist"]["measurement-auditor"]["by_tag"]["test-infra"]["runs"] == 1


# --- ledger: changes to the selection table --------------------------------------

SELECTION_RULE = """\
schema: 1
rules:
  - id: regex-performance-2
    category: regex-performance
    rung: selection
    specialist: fuzzer
    scope: project
    location: ".claude/agent-loop/selection.yml"
    summary: "Run the fuzzer for the parsers tag."
    added: 2026-11-10
    baseline: 2
    history: []
"""


def test_a_selection_rule_counts_its_specialists_catches_as_its_own(tmp_path):
    p = tmp_path / "rules-ledger.yml"
    p.write_text(SELECTION_RULE)
    recs = [{"date": "2026-11-12", "findings": [_f("regex-performance", "fuzzer"),
                                                _f("regex-performance", ["perf-tester", "fuzzer"]),
                                                _f("regex-performance", caught_by="human"),
                                                _f("regex-performance", "perf-tester")]}]
    (rule,) = ledger_report(load_ledger(p, "project"), recs, NOW)["rules"]
    assert rule["rung"] == "selection" and rule["specialist"] == "fuzzer"
    assert (rule["occurrences_since"], rule["caught_by_rule"], rule["escaped"]) == (4, 2, 2)


def test_a_selection_rule_without_a_specialist_counts_everything_as_escaped(tmp_path):
    p = tmp_path / "rules-ledger.yml"
    p.write_text(SELECTION_RULE.replace("    specialist: fuzzer\n", ""))
    recs = [{"date": "2026-11-12", "findings": [_f("regex-performance", "fuzzer")]}]
    (rule,) = ledger_report(load_ledger(p, "project"), recs, NOW)["rules"]
    assert (rule["caught_by_rule"], rule["escaped"]) == (0, 1)


def test_cli_reports_specialists_and_the_override(tmp_path):
    root = tmp_path / "repo"
    runs = root / ".claude" / "runs"
    runs.mkdir(parents=True)
    (runs / "2026-11-20-a.yml").write_text("""\
schema: 1
date: 2026-11-20
plan:
  units: ["u"]
  tags:
    - unit: "u"
      tags: [regex]
selection:
  - pool: tester
    round: 1
    tags: [regex]
    chosen: [test-runner, fuzzer]
    not_run:
      - specialist: perf-tester
        reason: opt-in
    budget:
      heavy_runs: 6
      heavy_minutes: 60
    used:
      heavy_runs: 1
      heavy_minutes: 2
findings:
  - stage: implement
    category: regex-performance
    severity: major
    detail: "x"
    caught_by: tester
    specialist: fuzzer
    fixed: true
""")
    (root / OVERRIDE_SELECTION).parent.mkdir(parents=True)
    (root / OVERRIDE_SELECTION).write_text("schema: 1\nenable: [perf-tester]\n")
    out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--since", "2026-11-01",
                          "--transcripts", str(tmp_path / "none.jsonl"), "--user-ledger", str(tmp_path / "none.yml")],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)["specialists"]
    assert data["selection"]["override"] == str(OVERRIDE_SELECTION)
    assert data["selection"]["errors"] == []
    assert data["by_specialist"]["fuzzer"]["findings"] == 1
    assert data["by_tag"]["regex"]["runs"] == 1


def test_the_documented_run_record_example_carries_the_specialist_fields():
    from record_gate import approval_failures, review_failures
    text = (PLUGIN / "docs/DESIGN.md").read_text()
    example = text.split("## Run record", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    rec = parse_yaml_lite(example)
    assert {e["pool"] for e in rec["selection"]} == {"tester", "reviewer"}
    assert rec["selection"][0]["not_run"][0]["reason"] == "opt-in"
    assert set(rec["selection"][0]["budget"]) == set(rec["selection"][0]["used"]) == {"heavy_runs", "heavy_minutes"}
    rep = specialist_report([rec], default())
    assert rep["by_specialist"]["correctness-reviewer"]["findings"] == 1
    assert rep["by_specialist"]["docs-reviewer"]["rejected"] == 1
    assert review_failures(rec) == [] and approval_failures(rec, required=True, repo=None, base=None) == []
