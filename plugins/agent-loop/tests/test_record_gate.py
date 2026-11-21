"""record_gate.py: the lead's mechanical check of a run record before it reports done."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from record_gate import main

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "record_gate.py"

DONE = """\
schema: 1
date: 2026-11-21
task: "Add a flag"
repo: proj
outcome: completed
rounds: 1
stages: [preflight, plan, test-write, implement, test, review, gate]
plan_approved: n/a
findings: []
"""


def _record(tmp_path, text=DONE, **replace):
    for old, new in replace.items():
        text = text.replace(old, new)
    p = tmp_path / "2026-11-21-add-a-flag.yml"
    p.write_text(text)
    return p


def _run(capsys, *args):
    code = main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out + out.err


# --- skipped-independent-review -------------------------------------------

def test_reviewed_final_diff_passes(tmp_path, capsys):
    code, out = _run(capsys, _record(tmp_path))
    assert code == 0, out


def test_no_review_stage_fails(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(", review, gate]", ", gate]"))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-independent-review" in out


@pytest.mark.parametrize("stages", [
    "[plan, implement, test, review, implement, test, gate]",
    "[plan, test-write, implement, test, review, test-write, test]",
    "[plan, implement, review, implement]",
])
def test_change_after_last_review_fails(tmp_path, capsys, stages):
    rec = _record(tmp_path, DONE.replace("[preflight, plan, test-write, implement, test, review, gate]", stages))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-independent-review" in out


def test_review_after_fix_round_passes(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(
        "[preflight, plan, test-write, implement, test, review, gate]",
        "[preflight, plan, implement, test, review, implement, test, review, gate]"))
    code, out = _run(capsys, rec)
    assert code == 0, out


def test_block_list_stages_are_read(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(
        "stages: [preflight, plan, test-write, implement, test, review, gate]\n",
        "stages:\n  - plan\n  - implement\n  - review\n"))
    code, out = _run(capsys, rec)
    assert code == 0, out


@pytest.mark.parametrize("stages", ["", "stages: []\n", "stages: review\n"])
def test_missing_or_malformed_stages_fail(tmp_path, capsys, stages):
    rec = _record(tmp_path, DONE.replace(
        "stages: [preflight, plan, test-write, implement, test, review, gate]\n", stages))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-independent-review" in out


# --- skipped-plan-approval: the record --------------------------------------

def test_missing_plan_approved_fails(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace("plan_approved: n/a\n", ""))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-plan-approval" in out and "plan_approved" in out


def test_not_applicable_fails_when_approval_required(tmp_path, capsys):
    code, out = _run(capsys, _record(tmp_path), "--require-plan-approval")
    assert code == 1
    assert "skipped-plan-approval" in out


@pytest.mark.parametrize("value", [
    '"2026-11-21T14:05:00+00:00"', "2026-11-21T14:05:00Z", "'2026-11-21T09:05:00-05:00'"])
def test_approval_time_passes_when_required(tmp_path, capsys, value):
    rec = _record(tmp_path, DONE.replace("plan_approved: n/a", f"plan_approved: {value}"))
    code, out = _run(capsys, rec, "--require-plan-approval")
    assert code == 0, out


@pytest.mark.parametrize("value", ["2026-11-21", "2026-11-21T14:05:00", "yes", "true", "soon"])
def test_approval_without_time_and_offset_fails(tmp_path, capsys, value):
    rec = _record(tmp_path, DONE.replace("plan_approved: n/a", f"plan_approved: {value}"))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-plan-approval" in out


def test_both_failures_are_reported_together(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(", review, gate]", "]").replace("plan_approved: n/a\n", ""))
    code, out = _run(capsys, rec)
    assert code == 1
    assert "skipped-independent-review" in out and "skipped-plan-approval" in out


# --- outcomes that do not report done ---------------------------------------

@pytest.mark.parametrize("outcome", ["in-progress", "abandoned"])
def test_not_done_outcomes_are_not_gated(tmp_path, capsys, outcome):
    rec = _record(tmp_path, DONE.replace("outcome: completed", f"outcome: {outcome}")
                  .replace(", review, gate]", "]").replace("plan_approved: n/a\n", ""))
    code, out = _run(capsys, rec)
    assert code == 0
    assert "not a done report" in out


# --- skipped-plan-approval: the commits -------------------------------------

def _git(repo, *args, date=None):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "work")
    _git(r, "commit", "-q", "--allow-empty", "-m", "base", date="2026-11-20T10:00:00+00:00")
    base = _git(r, "rev-parse", "HEAD")
    return r, base


APPROVED = DONE.replace("plan_approved: n/a", 'plan_approved: "2026-11-21T12:00:00+00:00"')


def test_commits_after_approval_pass(tmp_path, capsys, repo):
    r, base = repo
    _git(r, "commit", "-q", "--allow-empty", "-m", "unit 1", date="2026-11-21T12:30:00+00:00")
    code, out = _run(capsys, _record(tmp_path, APPROVED), "--require-plan-approval",
                     "--repo", r, "--base", base)
    assert code == 0, out


def test_commit_before_approval_fails(tmp_path, capsys, repo):
    r, base = repo
    # 13:30 in +02:00 is 11:30 UTC: before the 12:00 UTC approval.
    _git(r, "commit", "-q", "--allow-empty", "-m", "unit 1", date="2026-11-21T13:30:00+02:00")
    early = _git(r, "rev-parse", "--short", "HEAD")
    _git(r, "commit", "-q", "--allow-empty", "-m", "unit 2", date="2026-11-21T12:30:00+00:00")
    code, out = _run(capsys, _record(tmp_path, APPROVED), "--repo", r, "--base", base)
    assert code == 1
    assert "skipped-plan-approval" in out and early in out


def test_commits_before_base_are_ignored(tmp_path, capsys, repo):
    r, base = repo  # the base commit itself predates the approval
    code, out = _run(capsys, _record(tmp_path, APPROVED), "--repo", r, "--base", base)
    assert code == 0, out


def test_commit_check_needs_an_approval_time(tmp_path, capsys, repo):
    r, base = repo
    _git(r, "commit", "-q", "--allow-empty", "-m", "unit 1", date="2026-11-21T12:30:00+00:00")
    code, out = _run(capsys, _record(tmp_path), "--require-plan-approval", "--repo", r, "--base", base)
    assert code == 1
    assert "skipped-plan-approval" in out


# --- usage errors -----------------------------------------------------------

def test_unreadable_record_is_a_usage_error(tmp_path, capsys):
    code, out = _run(capsys, tmp_path / "missing.yml")
    assert code == 2


def test_malformed_record_is_a_usage_error(tmp_path, capsys):
    rec = _record(tmp_path, "schema: 1\n  oops: [\n")
    code, out = _run(capsys, rec)
    assert code == 2


@pytest.mark.parametrize("base", ["--output={out}", "-p"])
def test_option_shaped_base_is_refused(tmp_path, capsys, repo, base):
    r, _ = repo
    out_file = tmp_path / "written"
    code, out = _run(capsys, _record(tmp_path, APPROVED), "--repo", r, f"--base={base.format(out=out_file)}")
    assert code == 2
    assert not out_file.exists()


def test_unknown_base_is_a_usage_error(tmp_path, capsys, repo):
    r, _ = repo
    code, out = _run(capsys, _record(tmp_path, APPROVED), "--repo", r, "--base", "no-such-rev")
    assert code == 2


def test_repo_without_base_is_a_usage_error(tmp_path, capsys, repo):
    r, _ = repo
    with pytest.raises(SystemExit) as e:
        main([str(_record(tmp_path, APPROVED)), "--repo", str(r)])
    assert e.value.code == 2


def test_cli_end_to_end(tmp_path):
    rec = _record(tmp_path, DONE.replace(", review, gate]", "]"))
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), str(rec)], capture_output=True, text=True)
    assert p.returncode == 1
    assert "skipped-independent-review" in p.stderr
