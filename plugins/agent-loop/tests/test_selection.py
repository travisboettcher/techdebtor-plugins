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
    assert set(t["budget"]) == set(t["budget_max"]) == {"heavy_runs", "heavy_minutes"}
    assert all(0 < t["budget"][k] <= t["budget_max"][k] for k in t["budget"])
    assert set(t["retro"]) == {"drop_after_runs", "add_after_escapes"}
    for tag, row in t["tags"].items():
        assert set(row.get("floor", [])) <= set(row["run"]), tag
        assert set(row) <= {"when", "files", "run", "floor"}, tag
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


def test_guard_tags_have_a_floor_and_a_file_signal():
    # Safeguards that used to run unconditionally cannot be removed by a project's override,
    # and the changed files alone add their tags (the lead and the coordinators check `files`).
    t = default()["tags"]
    floors = {tag: row["floor"] for tag, row in t.items() if "floor" in row}
    assert floors == {"permissions": ["permissions-reviewer"], "regex": ["fuzzer"],
                      "test-infra": ["measurement-auditor"], "untrusted-input": ["security-reviewer"],
                      "security-sensitive": ["security-reviewer"]}
    assert set(floors) <= {tag for tag, row in t.items() if row.get("files")}
    assert "Not ordinary" in t["test-infra"]["when"]


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
    rows = re.findall(r"^\| `([a-z-]+)` \| [^|]+ \| ([^|]+) \| ([^|]*) \|$", section, re.M)
    shown = {tag: (re.findall(r"`([a-z-]+)`", run), re.findall(r"`([a-z-]+)`", floor)) for tag, run, floor in rows}
    assert shown == {tag: (row["run"], row.get("floor", [])) for tag, row in default()["tags"].items()}


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


HOSTILE = """\
schema: 1
baseline: []
budget:
  heavy_runs: 999
  heavy_minutes: 100000
budget_max:
  heavy_runs: 999
tags:
  permissions:
    when: "Never."
    run: []
  regex:
    run: []
  test-infra:
    run: [mutation-tester]
    floor: []
  untrusted-input:
    run: [fuzzer]
  security-sensitive:
    run: []
"""


def test_a_hostile_override_cannot_remove_the_floor_baseline_or_raise_the_budget():
    table, errors = merge_selection(default(), parse_yaml_lite(HOSTILE))
    d = default()
    assert table["baseline"] == d["baseline"]
    for tag, row in d["tags"].items():
        assert set(row.get("floor", [])) <= set(table["tags"][tag]["run"]), tag
        assert table["tags"][tag]["when"] == row["when"], tag
        assert table["tags"][tag].get("floor") == row.get("floor"), tag
    assert table["budget"] == d["budget_max"] and table["budget_max"] == d["budget_max"]
    text = " ".join(errors)
    for word in ("baseline", "budget_max", "heavy_runs", "heavy_minutes", "permissions-reviewer", "fuzzer",
                 "measurement-auditor", "security-reviewer", "`when`", "floor"):
        assert word in text, word
    # What an override may do still applies: rows can add specialists.
    assert "mutation-tester" in table["tags"]["test-infra"]["run"]


@pytest.mark.parametrize("over, expected, complaint", [
    ("budget:\n  heavy_runs: 3\n", {"heavy_runs": 3, "heavy_minutes": 60}, None),
    ("budget:\n  heavy_runs: 13\n", {"heavy_runs": 12, "heavy_minutes": 60}, "budget_max"),
    ("budget:\n  heavy_minutes: -1\n", {"heavy_runs": 6, "heavy_minutes": 60}, "heavy_minutes"),
])
def test_budget_overrides_are_clamped_to_the_ceiling(over, expected, complaint):
    table, errors = merge_selection(default(), parse_yaml_lite("schema: 1\n" + over))
    assert table["budget"] == expected
    assert (complaint is None and errors == []) or any(complaint in e for e in errors)


def test_retro_thresholds_can_be_tuned_within_reason():
    table, errors = merge_selection(default(), parse_yaml_lite(
        "schema: 1\nretro:\n  drop_after_runs: 10\n  add_after_escapes: 0\n  other: 3\n"))
    assert table["retro"] == {"drop_after_runs": 10, "add_after_escapes": 2}
    assert any("add_after_escapes" in e for e in errors) and any("other" in e for e in errors)


def test_unknown_override_keys_are_reported():
    _, errors = merge_selection(default(), parse_yaml_lite("schema: 1\nspecalists: []\n"))
    assert any("specalists" in e for e in errors)


def test_a_deeply_nested_override_is_an_error_not_a_crash(tmp_path):
    p = tmp_path / OVERRIDE_SELECTION
    p.parent.mkdir(parents=True)
    p.write_text("".join(" " * i + f"k{i}:\n" for i in range(3000)) + " " * 3000 + "v: 1\n")
    sel = load_selection(tmp_path)
    assert sel["errors"] and sel["table"]["tags"] == default()["tags"]


def test_an_unreadable_override_is_an_error_not_a_crash(tmp_path):
    p = tmp_path / OVERRIDE_SELECTION
    p.mkdir(parents=True)  # a directory where the file should be
    (p / "x").write_text("")
    sel = load_selection(tmp_path)
    assert sel["table"]["tags"] == default()["tags"]


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

def _chosen(chosen, tags):
    """Chosen entries: each specialist selected by the run's tags it serves (or the baseline)."""
    table = default()
    out = []
    for name in chosen:
        by = [t for t in tags if name in table["tags"][t]["run"]] or ["baseline"]
        out.append({"specialist": name, "by": by})
    return out


def _rec(tags, chosen, findings=(), rejected=(), date="2026-11-20"):
    return {"date": date, "plan": {"units": ["u"], "tags": [{"unit": "u", "tags": list(tags)}]},
            "selection": [{"pool": "tester", "round": 1, "chosen": _chosen(chosen, tags)}],
            "findings": list(findings), "rejected": list(rejected)}


def _f(category, specialist=None, caught_by="tester", round=None):
    f = {"stage": "implement", "category": category, "severity": "major", "caught_by": caught_by}
    if specialist is not None:
        f["specialist"] = specialist
    if round is not None:
        f["round"] = round
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
    assert s["by_tag"]["regex"] == {"runs": 1, "findings": 1, "rejected": 0, "misses": 1, "overlap": 0}


@pytest.mark.parametrize("finding, miss, overlap", [
    (_f("regex-performance", "perf-tester"), 0, 1),                       # another specialist, same round
    (_f("regex-performance", "perf-tester", round=1), 0, 1),
    (_f("regex-performance", "perf-tester", round=2), 1, 0),              # a later round: it escaped round 1
    (_f("regex-performance", caught_by="hook"), 1, 0),
    (_f("regex-performance", caught_by="ci"), 1, 0),
    (_f("regex-performance", caught_by="lead"), 0, 1),
])
def test_a_miss_escaped_the_swarm_and_same_run_overlap_is_separate(finding, miss, overlap):
    s = specialist_report([_rec(["regex"], ["fuzzer"], findings=[finding])], default())["by_specialist"]["fuzzer"]
    assert (s["misses"], s["overlap"]) == (miss, overlap)


def test_by_tag_credits_only_the_tags_that_selected_the_specialist():
    rec = _rec(["regex", "ui"], ["fuzzer", "test-runner"], findings=[_f("regex-performance", "fuzzer")])
    rep = specialist_report([rec], default())["by_specialist"]
    assert set(rep["fuzzer"]["by_tag"]) == {"regex"}
    assert rep["test-runner"]["by_tag"] == {}           # the baseline: no tag chose it
    assert rep["test-runner"]["runs"] == 1


def test_plain_name_entries_still_count_without_tag_credit():
    rec = _rec(["regex"], [], findings=[_f("regex-performance", "fuzzer")])
    rec["selection"][0]["chosen"] = ["fuzzer"]
    s = specialist_report([rec], default())["by_specialist"]["fuzzer"]
    assert (s["runs"], s["findings"], s["by_tag"]) == (1, 1, {})


def test_a_specialist_not_chosen_has_no_misses():
    recs = [_rec([], ["test-runner"], findings=[_f("regex-performance", caught_by="ci")])]
    rep = specialist_report(recs, default())
    assert "fuzzer" not in rep["by_specialist"]
    assert rep["by_specialist"]["test-runner"]["misses"] == 0


def test_merged_findings_credit_every_specialist_that_reported_them():
    recs = [_rec(["untrusted-input"], ["fuzzer"], findings=[_f("unhandled-input", ["fuzzer", "security-reviewer"])])]
    recs[0]["selection"].append({"pool": "reviewer", "round": 1,
                                 "chosen": _chosen(["correctness-reviewer", "security-reviewer"], ["untrusted-input"])})
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
            {"date": "2026-11-04", "selection": [{"chosen": "fuzzer"}, None, {"chosen": [None, 3, {"by": 1}]},
                                                 {"round": "x", "chosen": [{"specialist": "fuzzer", "by": "regex"}]}],
             "findings": [_f("regex-performance", specialist=7)]}]
    rep = specialist_report(recs, default())
    assert rep["records"] == 2
    assert rep["by_specialist"]["fuzzer"]["runs"] == 2


def test_diff_derived_tags_in_a_selection_entry_count():
    rec = _rec([], ["measurement-auditor"])
    rec["selection"][0]["tags"] = ["test-infra"]
    rec["selection"][0]["chosen"] = [{"specialist": "measurement-auditor", "by": ["test-infra"]}]
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


def test_a_rule_that_drops_a_specialist_is_judged_on_escapes_in_its_category(tmp_path):
    p = tmp_path / "rules-ledger.yml"
    p.write_text(SELECTION_RULE.replace("    specialist: fuzzer\n", "    specialist: fuzzer\n    change: drop\n"))
    recs = [{"date": "2026-11-12", "findings": [_f("regex-performance", "fuzzer"),          # caught anyway
                                                _f("regex-performance", "perf-tester"),     # caught by the swarm
                                                _f("regex-performance", caught_by="human"),  # escaped: the drop hurt
                                                _f("regex-performance", caught_by="ci")]}]
    (rule,) = ledger_report(load_ledger(p, "project"), recs, NOW)["rules"]
    assert (rule["occurrences_since"], rule["caught_by_rule"], rule["escaped"]) == (4, 2, 2)


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
    chosen:
      - specialist: test-runner
        by: [baseline]
      - specialist: fuzzer
        by: [regex]
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
    assert data["by_specialist"]["fuzzer"]["by_tag"]["regex"]["findings"] == 1
    assert data["selection"]["retro"] == {"drop_after_runs": 5, "add_after_escapes": 2}


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


def test_the_lead_tags_units_and_briefs_both_coordinators_with_the_table():
    text = (PLUGIN / "skills/lead/SKILL.md").read_text()
    assert "**Risk tags**" in text
    assert "${CLAUDE_PLUGIN_ROOT}/docs/selection.yml" in text and str(OVERRIDE_SELECTION) in text
    assert "`agent-loop:tester` coordinator" in text and "`agent-loop:reviewer` coordinator" in text
    assert "`selection`" in text and "`specialist`" in text and "report_only" in text


def test_the_retro_proposes_selection_changes_as_ledger_rules():
    text = (PLUGIN / "skills/retro/SKILL.md").read_text()
    assert "rung: selection" in text and str(OVERRIDE_SELECTION) in text
    assert "precision" in text and "miss_rate" in text


def test_baseline_and_verify_skills_are_not_tags():
    rec = _rec([], [])
    rec["selection"][0]["chosen"] = [{"specialist": "check-runner", "by": ["verify-skills"]},
                                     {"specialist": "test-runner", "by": "baseline"},
                                     {"specialist": "security-reviewer", "by": ["escalation"]}]
    rep = specialist_report([rec], default())["by_specialist"]
    assert rep["check-runner"]["by_tag"] == {} and rep["test-runner"]["by_tag"] == {}
    assert rep["security-reviewer"]["by_tag"] == {} and rep["security-reviewer"]["runs"] == 1


def test_the_lead_has_a_fast_path_and_ignores_report_only_when_halting():
    text = (PLUGIN / "skills/lead/SKILL.md").read_text()
    fast = text.split("**Fast path.**", 1)[1].split("\n## ", 1)[0]
    assert "`agent-loop:test-runner`" in fast and "`agent-loop:correctness-reviewer`" in fast
    assert "verification-rules.md" in fast and "review-rules.md" in fast and "`files` signal" in fast
    assert "When the review starts (coordinator or fast path)" in text
    assert "all blocking checks passing" in text and "blocking check BLOCKED" in text
