"""Test levels in run records: each criterion's target level in the plan, and the level that should have caught a finding."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from retro_mine import LEVELS, level_report

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "retro_mine.py"


def _f(category, level=None, caught_by="human", round=None):
    f = {"stage": "implement", "category": category, "severity": "major", "caught_by": caught_by}
    if level is not None:
        f["should_have_caught_at"] = level
    if round is not None:
        f["round"] = round
    return f


def _rec(findings=(), test_plan=None, date="2026-11-20"):
    rec = {"date": date, "findings": list(findings)}
    if test_plan is not None:
        rec["plan"] = {"units": ["u"], "test_plan": test_plan}
    return rec


def test_the_levels_are_the_designs():
    assert LEVELS == ("unit", "component", "contract", "integration", "system")
    design = (PLUGIN / "docs/DESIGN.md").read_text().split("## Test levels", 1)[1].split("\n## ", 1)[0]
    for level in LEVELS:
        assert f"| `{level}` |" in design, level


def test_records_without_levels_give_an_empty_report():
    rep = level_report([_rec([_f("logic-error")]), {"date": "2026-11-01"}])
    assert rep == {"levels": list(LEVELS), "planned": {}, "by_level": {}, "invalid": 0}


def test_escapes_are_counted_per_level_with_their_categories():
    recs = [_rec([_f("missing-contract-test", "contract"), _f("interface-mismatch", "contract", caught_by="ci"),
                  _f("logic-error", "unit", caught_by="tester")]),
            _rec([_f("missing-contract-test", "contract", caught_by="dispatcher")]),
            _rec([_f("logic-error", "unit", caught_by="tester", round=2)])]
    by = level_report(recs)["by_level"]
    assert by["contract"] == {"findings": 3, "escaped": 3, "runs_escaped": 2,
                              "categories": {"missing-contract-test": 2, "interface-mismatch": 1}}
    # Caught by the swarm in the first round: attributed to a level, but not an escape.
    # Caught in a later round: it got past the first round's checks.
    assert by["unit"] == {"findings": 2, "escaped": 1, "runs_escaped": 1, "categories": {"logic-error": 2}}


def test_planned_criteria_are_counted_per_target_level():
    plan = [{"criterion": "a", "test": "t::a", "level": "unit", "unit": "u"},
            {"criterion": "b", "test": "t::b", "level": "unit", "unit": "u"},
            {"criterion": "c", "test": "t::c", "level": "system", "unit": "u"},
            {"criterion": "d", "test": "t::d", "unit": "u"}]          # no level: older plans
    assert level_report([_rec(test_plan=plan)])["planned"] == {"unit": 2, "system": 1}


@pytest.mark.parametrize("bad", ["e2e", "Unit", "", 3, ["unit"], {"level": "unit"}, None])
def test_unknown_levels_are_counted_as_invalid_never_echoed(bad):
    recs = [_rec([{**_f("logic-error"), "should_have_caught_at": bad}],
                 test_plan=[{"criterion": "a", "level": bad}])]
    rep = level_report(recs)
    assert rep["by_level"] == {} and rep["planned"] == {}
    assert rep["invalid"] == (0 if bad is None else 2)
    assert "e2e" not in json.dumps(rep)


def test_odd_shapes_do_not_crash():
    recs = [{"date": "2026-11-01", "plan": ".claude/runs/x.plan.md", "findings": None},
            {"date": "2026-11-02", "plan": {"test_plan": "nope"}, "findings": "nope"},
            {"date": "2026-11-03", "plan": {"test_plan": [None, 3, "x", {"level": "unit"}]},
             "findings": [None, 3, {"should_have_caught_at": "unit", "category": 7}]}]
    rep = level_report(recs)
    assert rep["planned"] == {"unit": 1}
    assert rep["by_level"]["unit"] == {"findings": 1, "escaped": 0, "runs_escaped": 0, "categories": {}}


def test_many_records_are_counted_in_linear_time():
    recs = [_rec([_f("missing-contract-test", "contract")] * 50,
                 test_plan=[{"criterion": "a", "level": "unit"}] * 50) for _ in range(4000)]
    start = time.monotonic()
    rep = level_report(recs)
    assert time.monotonic() - start < 2
    assert rep["by_level"]["contract"]["runs_escaped"] == 4000 and rep["planned"]["unit"] == 200000


def test_cli_reports_test_levels(tmp_path):
    root = tmp_path / "repo"
    runs = root / ".claude" / "runs"
    runs.mkdir(parents=True)
    (runs / "2026-11-20-a.yml").write_text("""\
schema: 1
date: 2026-11-20
plan:
  units: ["u"]
  test_plan:
    - criterion: "When x, the exporter shall y."
      test: tests/test_x.py::test_y
      level: component
      unit: "u"
findings:
  - stage: plan
    category: missing-contract-test
    severity: major
    detail: "x"
    caught_by: human
    should_have_caught_at: contract
    fixed: false
""")
    out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--since", "2026-11-01",
                          "--transcripts", str(tmp_path / "none.jsonl"), "--user-ledger", str(tmp_path / "none.yml")],
                         capture_output=True, text=True, check=True)
    levels = json.loads(out.stdout)["test_levels"]
    assert levels["planned"] == {"component": 1}
    assert levels["by_level"]["contract"]["runs_escaped"] == 1


def test_the_retro_proposes_tests_at_the_level_where_escapes_repeat():
    text = (PLUGIN / "skills/retro/SKILL.md").read_text()
    assert "`test_levels`" in text and "should_have_caught_at" in text and "runs_escaped" in text
