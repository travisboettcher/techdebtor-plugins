"""record_gate.py: the lead's mechanical check of a run record before it reports done.

Exit codes: 0 pass; 1 review missing or stale; 2 cannot check; 3 skipped plan approval.
"""

import os
import shutil
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
STAGES = "[preflight, plan, test-write, implement, test, review, gate]"
APPROVED = DONE.replace("plan_approved: n/a", 'plan_approved: "2026-11-21T12:00:00+00:00"')


def _record(tmp_path, text=DONE, extra=""):
    p = tmp_path / "2026-11-21-add-a-flag.yml"
    p.write_text(text + extra)
    return p


def _run(capsys, *args):
    code = main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out + out.err


def _check(capsys, *args):
    return _run(capsys, "check", *args)


def _env(date=None):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return env


def _git(repo, *args, date=None):
    return subprocess.run(["git", "-C", str(repo), *args], env=_env(date), check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(repo, msg, date, path=None):
    if path:
        (repo / path).write_text(msg + "\n")
        _git(repo, "add", path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", msg, date=date)
    return _git(repo, "rev-parse", "--short", "HEAD")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "work")
    _commit(r, "base", "2026-11-20T10:00:00+00:00", "a.txt")
    return r, _git(r, "rev-parse", "HEAD")


def _fingerprint(capsys, r, base):
    code, out = _run(capsys, "fingerprint", "--repo", r, "--base", base)
    assert code == 0, out
    return out.strip()


# --- skipped-independent-review: stage order (records without reviewed_diff) ---

def test_reviewed_final_diff_passes(tmp_path, capsys):
    code, out = _check(capsys, _record(tmp_path))
    assert code == 0, out


def test_no_review_stage_fails(tmp_path, capsys):
    code, out = _check(capsys, _record(tmp_path, DONE.replace(", review, gate]", ", gate]")))
    assert code == 1
    assert "skipped-independent-review" in out


@pytest.mark.parametrize("stages", [
    "[plan, implement, test, review, implement, test, gate]",
    "[plan, test-write, implement, test, review, test-write, test]",
    "[plan, implement, review, implement]",
])
def test_change_after_last_review_fails(tmp_path, capsys, stages):
    code, out = _check(capsys, _record(tmp_path, DONE.replace(STAGES, stages)))
    assert code == 1
    assert "skipped-independent-review" in out


def test_review_after_fix_round_passes(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(STAGES, "[preflight, plan, implement, test, review, implement, test, review, gate]"))
    code, out = _check(capsys, rec)
    assert code == 0, out


def test_block_list_stages_are_read(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(f"stages: {STAGES}\n", "stages:\n  - plan\n  - implement\n  - review\n"))
    code, out = _check(capsys, rec)
    assert code == 0, out


@pytest.mark.parametrize("stages", ["", "stages: []\n", "stages: review\n"])
def test_missing_or_malformed_stages_fail(tmp_path, capsys, stages):
    code, out = _check(capsys, _record(tmp_path, DONE.replace(f"stages: {STAGES}\n", stages)))
    assert code == 1
    assert "skipped-independent-review" in out


# --- skipped-independent-review: the reviewed change's fingerprint -------------

def test_fingerprint_is_stable_and_shaped(capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    fp = _fingerprint(capsys, r, base)
    assert fp.startswith("sha256:") and len(fp) == len("sha256:") + 64
    assert _fingerprint(capsys, r, base) == fp


def test_fingerprint_does_not_touch_the_index(capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    index = r / ".git" / "index"
    before = index.read_bytes(), index.stat().st_mtime_ns
    _fingerprint(capsys, r, base)
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


@pytest.mark.parametrize("change", [
    lambda r: (r / "a.txt").write_text("edited again\n"),           # tracked edit
    lambda r: (r / "new.txt").write_text("untracked\n"),             # new untracked file
    lambda r: (r / "blob.bin").write_bytes(b"\x00\x01\x02\xff"),     # new binary file
])
def test_fingerprint_changes_with_the_change(capsys, repo, change):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    (r / "old.bin").write_bytes(b"\x00\xfe")
    before = _fingerprint(capsys, r, base)
    change(r)
    assert _fingerprint(capsys, r, base) != before


def test_fingerprint_sees_binary_and_untracked_content(capsys, repo):
    r, base = repo
    (r / "blob.bin").write_bytes(b"\x00\x01")
    before = _fingerprint(capsys, r, base)
    (r / "blob.bin").write_bytes(b"\x00\x02")
    assert _fingerprint(capsys, r, base) != before
    _git(r, "add", "blob.bin")
    _commit(r, "bin", "2026-11-21T12:30:00+00:00")
    after_commit = _fingerprint(capsys, r, base)
    (r / "blob.bin").write_bytes(b"\x00\x03")
    assert _fingerprint(capsys, r, base) != after_commit


def test_committing_the_reviewed_change_keeps_the_fingerprint(capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    before = _fingerprint(capsys, r, base)
    _git(r, "add", "a.txt")
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00")
    assert _fingerprint(capsys, r, base) == before


def test_run_records_are_outside_the_fingerprint(capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    before = _fingerprint(capsys, r, base)
    (r / ".claude" / "runs").mkdir(parents=True)
    (r / ".claude" / "runs" / "2026-11-21-x.yml").write_text("schema: 1\n")
    assert _fingerprint(capsys, r, base) == before


def _reviewed(tmp_path, capsys, r, base):
    fp = _fingerprint(capsys, r, base)
    return _record(tmp_path, DONE, f"base: {base}\nreviewed_diff: \"{fp}\"\n")


def test_unchanged_since_review_passes(tmp_path, capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    rec = _reviewed(tmp_path, capsys, r, base)
    code, out = _check(capsys, rec, "--repo", r)
    assert code == 0, out


def test_change_after_review_fails_even_with_good_stages(tmp_path, capsys, repo):
    r, base = repo
    (r / "a.txt").write_text("changed\n")
    rec = _reviewed(tmp_path, capsys, r, base)
    (r / "late.txt").write_text("added after the review\n")
    code, out = _check(capsys, rec, "--repo", r)
    assert code == 1
    assert "skipped-independent-review" in out and "changed since" in out


def test_reviewed_diff_without_base_cannot_be_checked(tmp_path, capsys, repo):
    r, _ = repo
    rec = _record(tmp_path, DONE, 'reviewed_diff: "sha256:' + "0" * 64 + '"\n')
    code, out = _check(capsys, rec, "--repo", r)
    assert code == 2


# --- skipped-plan-approval: the record ----------------------------------------

def test_missing_plan_approved_fails(tmp_path, capsys):
    code, out = _check(capsys, _record(tmp_path, DONE.replace("plan_approved: n/a\n", "")))
    assert code == 3
    assert "skipped-plan-approval" in out and "plan_approved" in out


def test_not_applicable_fails_when_approval_required(tmp_path, capsys):
    code, out = _check(capsys, _record(tmp_path), "--require-plan-approval")
    assert code == 3
    assert "skipped-plan-approval" in out and "human" in out


def test_a_delegated_record_always_requires_approval(tmp_path, capsys):
    # A run the dispatcher started always needed the human's approval, with or without the flag.
    code, out = _check(capsys, _record(tmp_path, DONE + "delegated: true\n"))
    assert code == 3
    assert "skipped-plan-approval" in out and "delegated" in out


@pytest.mark.parametrize("extra, code", [("delegated: true\n", 0), ("delegated: false\n", 0), ("", 0)])
def test_a_delegated_record_with_an_approval_time_passes(tmp_path, capsys, extra, code):
    assert _check(capsys, _record(tmp_path, APPROVED + extra))[0] == code


def test_not_applicable_passes_when_not_delegated(tmp_path, capsys):
    assert _check(capsys, _record(tmp_path, DONE + "delegated: false\n"))[0] == 0


@pytest.mark.parametrize("value", ["yes", '"true"', "1"])
def test_a_delegated_value_that_is_not_a_boolean_cannot_be_checked(tmp_path, capsys, value):
    code, out = _check(capsys, _record(tmp_path, APPROVED + f"delegated: {value}\n"))
    assert code == 2 and "delegated" in out
    # ... and never loosens the gate: it still requires the approval.
    assert _check(capsys, _record(tmp_path, DONE + f"delegated: {value}\n"))[0] == 3


@pytest.mark.parametrize("value", [
    '"2026-11-21T14:05:00+00:00"', "2026-11-21T14:05:00Z", "'2026-11-21T09:05:00-05:00'"])
def test_approval_time_passes_when_required(tmp_path, capsys, value):
    rec = _record(tmp_path, DONE.replace("plan_approved: n/a", f"plan_approved: {value}"))
    code, out = _check(capsys, rec, "--require-plan-approval")
    assert code == 0, out


@pytest.mark.parametrize("value", ["2026-11-21", "2026-11-21T14:05:00", "yes", "true", "soon"])
def test_approval_without_time_and_offset_fails(tmp_path, capsys, value):
    code, out = _check(capsys, _record(tmp_path, DONE.replace("plan_approved: n/a", f"plan_approved: {value}")))
    assert code == 3
    assert "skipped-plan-approval" in out


def test_plan_approval_outranks_a_missing_review(tmp_path, capsys):
    rec = _record(tmp_path, DONE.replace(", review, gate]", "]").replace("plan_approved: n/a\n", ""))
    code, out = _check(capsys, rec)
    assert code == 3
    assert "skipped-independent-review" in out and "skipped-plan-approval" in out


# --- outcomes that do not report done ---------------------------------------

@pytest.mark.parametrize("outcome", ["in-progress", "abandoned"])
def test_not_done_outcomes_are_not_gated(tmp_path, capsys, outcome):
    rec = _record(tmp_path, DONE.replace("outcome: completed", f"outcome: {outcome}")
                  .replace(", review, gate]", "]").replace("plan_approved: n/a\n", ""))
    code, out = _check(capsys, rec)
    assert code == 0
    assert "not a done report" in out


# --- skipped-plan-approval: the run's own commits ----------------------------

def test_commits_after_approval_pass(tmp_path, capsys, repo):
    r, base = repo
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00")
    code, out = _check(capsys, _record(tmp_path, APPROVED), "--require-plan-approval", "--repo", r, "--base", base)
    assert code == 0, out


def test_commit_before_approval_fails(tmp_path, capsys, repo):
    r, base = repo
    # 13:30 in +02:00 is 11:30 UTC: before the 12:00 UTC approval.
    early = _commit(r, "unit 1", "2026-11-21T13:30:00+02:00")
    _commit(r, "unit 2", "2026-11-21T12:30:00+00:00")
    code, out = _check(capsys, _record(tmp_path, APPROVED), "--repo", r, "--base", base)
    assert code == 3
    assert "skipped-plan-approval" in out and early in out


def test_base_is_read_from_the_record_and_the_flag_overrides(tmp_path, capsys, repo):
    r, base = repo
    _commit(r, "unit 1", "2026-11-21T11:00:00+00:00")
    mid = _git(r, "rev-parse", "HEAD")
    rec = _record(tmp_path, APPROVED, f"base: {base}\n")
    code, out = _check(capsys, rec, "--repo", r)
    assert code == 3
    code, out = _check(capsys, rec, "--repo", r, "--base", mid)
    assert code == 0, out


def test_commits_before_base_are_ignored(tmp_path, capsys, repo):
    r, base = repo  # the base commit itself predates the approval
    code, out = _check(capsys, _record(tmp_path, APPROVED), "--repo", r, "--base", base)
    assert code == 0, out


def test_trunk_commits_merged_in_are_not_the_runs(tmp_path, capsys, repo):
    r, base = repo
    _git(r, "branch", "trunk")
    _git(r, "switch", "-q", "trunk")
    _commit(r, "trunk work", "2026-11-21T09:00:00+00:00", "t.txt")
    _git(r, "switch", "-q", "work")
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00", "u.txt")
    _git(r, "merge", "-q", "--no-edit", "trunk", date="2026-11-21T12:40:00+00:00")
    rec = _record(tmp_path, APPROVED, f"base: {base}\ntrunk: trunk\n")
    code, out = _check(capsys, rec, "--repo", r)
    assert code == 0, out
    # without the trunk ref the trunk commit is counted
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 3


def test_merge_commits_are_skipped(tmp_path, capsys, repo):
    r, base = repo
    _git(r, "branch", "side")
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00", "u.txt")
    _git(r, "switch", "-q", "side")
    _commit(r, "side", "2026-11-21T12:35:00+00:00", "s.txt")
    _git(r, "switch", "-q", "work")
    # the merge commit itself is dated before the approval
    _git(r, "merge", "-q", "--no-edit", "side", date="2026-11-21T11:00:00+00:00")
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 0, out


def test_base_no_longer_an_ancestor_is_reported(tmp_path, capsys, repo):
    r, base = repo
    _git(r, "switch", "-q", "--orphan", "other")
    _commit(r, "unrelated", "2026-11-21T12:30:00+00:00", "o.txt")
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 2
    assert "not an ancestor" in out


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen to sign a commit")
def test_signed_commit_display_does_not_break_parsing(tmp_path, capsys, repo):
    # With log.showSignature=true, git log prints signature lines among the formatted ones.
    r, base = repo
    key = tmp_path / "signing-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    _git(r, "config", "gpg.format", "ssh")
    _git(r, "config", "user.signingkey", str(key))
    _git(r, "config", "gpg.ssh.allowedSignersFile", os.devnull)
    _git(r, "commit", "-q", "-S", "--allow-empty", "-m", "unit 1", date="2026-11-21T12:30:00+00:00")
    _git(r, "config", "log.showSignature", "true")
    assert "signature" in _git(r, "log", "-1", "--format=%h %aI")  # the display really is on
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 0, out


def test_commit_check_needs_an_approval_time(tmp_path, capsys, repo):
    r, base = repo
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00")
    code, out = _check(capsys, _record(tmp_path), "--require-plan-approval", "--repo", r, "--base", base)
    assert code == 3


# --- cannot check -------------------------------------------------------------

def test_unreadable_record_cannot_be_checked(tmp_path, capsys):
    code, out = _check(capsys, tmp_path / "missing.yml")
    assert code == 2


def test_malformed_record_cannot_be_checked(tmp_path, capsys):
    code, out = _check(capsys, _record(tmp_path, "schema: 1\n  oops: [\n"))
    assert code == 2


@pytest.mark.parametrize("flag", ["--base", "--trunk"])
@pytest.mark.parametrize("value", ["--output={out}", "-p"])
def test_option_shaped_revisions_are_refused(tmp_path, capsys, repo, flag, value):
    r, base = repo
    out_file = tmp_path / "written"
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r,
                       f"{flag}={value.format(out=out_file)}")
    assert code == 2
    assert not out_file.exists()


@pytest.mark.parametrize("extra", ["base: no-such-rev\n", "trunk: no-such-ref\n"])
def test_unknown_revisions_cannot_be_checked(tmp_path, capsys, repo, extra):
    r, base = repo
    text = APPROVED + (extra if extra.startswith("base") else f"base: {base}\n" + extra)
    code, out = _check(capsys, _record(tmp_path, text), "--repo", r)
    assert code == 2


def test_not_a_repository_cannot_be_checked(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out = _check(capsys, _record(tmp_path, APPROVED, "base: abc123\n"), "--repo", plain)
    assert code == 2


def test_unparsable_git_output_cannot_be_checked(tmp_path, capsys, repo, monkeypatch):
    import record_gate
    r, base = repo
    _commit(r, "unit 1", "2026-11-21T12:30:00+00:00")
    real = record_gate._git

    def garbled(repo_dir, *args, **kw):
        out = real(repo_dir, *args, **kw)
        return b"gpg: garbage line\n" + out if "log" in args else out
    monkeypatch.setattr(record_gate, "_git", garbled)
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 2


def test_missing_git_cannot_be_checked(tmp_path, capsys, repo, monkeypatch):
    r, base = repo
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    code, out = _check(capsys, _record(tmp_path, APPROVED, f"base: {base}\n"), "--repo", r)
    assert code == 2


def test_fingerprint_needs_a_base(capsys, repo):
    r, _ = repo
    with pytest.raises(SystemExit) as e:
        main(["fingerprint", "--repo", str(r)])
    assert e.value.code == 2


def test_cli_end_to_end(tmp_path):
    rec = _record(tmp_path, DONE.replace(", review, gate]", "]"))
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), "check", str(rec)], capture_output=True, text=True)
    assert p.returncode == 1
    assert "skipped-independent-review" in p.stderr
    assert "Traceback" not in p.stderr
