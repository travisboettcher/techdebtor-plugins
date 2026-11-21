#!/usr/bin/env python3
"""Check a run record before the lead reports done (docs/DESIGN.md, "Gates").

``record_gate.py fingerprint --base <sha> [--repo DIR]`` prints a fingerprint
of the change since ``<base>``: tracked changes (committed or not, via
``git diff --binary <base>``) plus every untracked file's path and content,
leaving out ``.claude/runs/``. The lead records it as ``reviewed_diff`` when
the reviewer runs. It never writes the index or anything else.

``record_gate.py check <record> [--repo DIR] [--base REV] [--trunk REF]
[--require-plan-approval]`` checks the record. ``--base`` and ``--trunk``
override the record's ``base`` and ``trunk``.

- ``skipped-independent-review``: with ``reviewed_diff``, the change's current
  fingerprint must equal it. Without it (older records), ``stages`` must list a
  ``review`` after the last ``implement`` or ``test-write``.
- ``skipped-plan-approval``: ``plan_approved`` is the time the human approved
  the plan (ISO 8601 with a UTC offset), or ``n/a`` when no approval was
  required; ``--require-plan-approval`` refuses ``n/a``. With a base, the run's
  own commits (``<base>..HEAD``, not merges, not reachable from the trunk) must
  not be authored before it. Author dates are advisory: a rebase with
  ``--reset-author`` or ``--ignore-date`` rewrites them.

Records whose ``outcome`` is ``in-progress`` or ``abandoned`` are not done
reports and are not gated.

Exit codes: 0 pass; 1 review missing or stale; 2 cannot check (git missing,
not a repository, unknown or rebased-away base, unparsable output, unreadable
record); 3 skipped plan approval. When several apply: 3, then 2, then 1.
Standard library only; reads the record with retro_mine's YAML subset parser.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import string
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retro_mine import YamlLiteError, parse_yaml_lite  # noqa: E402

CHANGE_STAGES = ("implement", "test-write")
NOT_DONE = ("in-progress", "abandoned")
RUNS_EXCLUDE = ":(top,exclude).claude/runs"
HUMAN_APPROVAL = ("the human's approval of the plan (in a delegated run, the human's answer relayed by the "
                  "delegator; an agent's approval never counts)")


class CannotCheck(Exception):
    pass


# --- git ----------------------------------------------------------------------

def _git(repo: str, *args: str) -> bytes:
    """stdout of a read-only git command; CannotCheck on any failure."""
    cmd = ["git", "-C", repo, "--no-optional-locks", "-c", "log.showSignature=false", *args]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise CannotCheck(f"cannot run git: {e}") from None
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip()[:200]
        raise CannotCheck(f"git {args[0]} failed: {err}")
    return out.stdout


def _is_sha(s: str) -> bool:
    return len(s) in (40, 64) and all(c in string.hexdigits for c in s)


def _rev(repo: str, rev: str, what: str) -> str:
    """The full commit id ``rev`` names; refuses option-shaped revisions."""
    if not isinstance(rev, str) or not rev.strip() or rev.startswith("-"):
        raise CannotCheck(f"{what} must be a revision, not {rev!r}")
    try:
        sha = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}")
    except CannotCheck:
        raise CannotCheck(f"{what} {rev!r} is not a commit in {repo}") from None
    sha = sha.decode("ascii", "replace").strip()
    if not _is_sha(sha):
        raise CannotCheck(f"unparsable git rev-parse output for {what}")
    return sha


def _is_ancestor(repo: str, base: str) -> bool:
    try:
        out = subprocess.run(["git", "-C", repo, "--no-optional-locks", "merge-base", "--is-ancestor",
                              base, "HEAD"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise CannotCheck(f"cannot run git: {e}") from None
    if out.returncode not in (0, 1):
        raise CannotCheck("git merge-base failed")
    return out.returncode == 0


def _toplevel(repo: str) -> str:
    top = _git(repo, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()
    if not top:
        raise CannotCheck(f"{repo} is not in a git repository")
    return top


def fingerprint(repo: str, base: str) -> str:
    top = _toplevel(repo)
    base = _rev(top, base, "base")
    h = hashlib.sha256()
    diff = _git(top, "diff", "--binary", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
                "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", "--diff-algorithm=myers", "-U3",
                "--end-of-options", base, "--", ":/", RUNS_EXCLUDE)
    h.update(b"diff\0" + len(diff).to_bytes(8, "big") + diff)
    listing = _git(top, "ls-files", "-z", "--others", "--exclude-standard", "--", ":/", RUNS_EXCLUDE)
    for rel in sorted(p for p in listing.split(b"\0") if p):
        path = os.path.join(os.fsencode(top), rel)
        try:
            if os.path.islink(path):
                kind, data = b"link", os.fsencode(os.readlink(path))
            elif os.path.isdir(path):
                kind, data = b"dir", b""
            else:
                with open(path, "rb") as f:
                    kind, data = b"file", f.read()
        except OSError as e:
            raise CannotCheck(f"cannot read untracked file {os.fsdecode(rel)}: {e}") from None
        h.update(b"untracked\0" + rel + b"\0" + kind + b"\0" + len(data).to_bytes(8, "big") + data)
    return "sha256:" + h.hexdigest()


def run_commits(repo: str, base: str, trunk: str | None) -> list[tuple[str, datetime]]:
    """The run's own commits: ``<base>..HEAD``, no merges, none reachable from ``trunk``."""
    base = _rev(repo, base, "base")
    if not _is_ancestor(repo, base):
        raise CannotCheck(f"base {base[:12]} is not an ancestor of HEAD (rebased?); "
                          "re-record base after a rebase")
    excl = [f"^{_rev(repo, trunk, 'trunk')}"] if trunk else []
    out = _git(repo, "log", "--no-show-signature", "--no-merges", "--no-color", "--format=%H %aI",
               "--end-of-options", f"{base}..HEAD", *excl)
    commits = []
    for line in out.decode("utf-8", "replace").splitlines():
        sha, sep, stamp = line.partition(" ")
        try:
            if not sep or not _is_sha(sha):
                raise ValueError
            when = datetime.fromisoformat(stamp.strip())
        except ValueError:
            raise CannotCheck(f"unparsable git log output: {line[:80]!r}") from None
        commits.append((sha, when))
    return commits


# --- the gates ----------------------------------------------------------------

def review_failures(rec: dict) -> list[str]:
    """The stage-order check, for records without ``reviewed_diff``."""
    stages = rec.get("stages")
    if not isinstance(stages, list) or not stages:
        return ["skipped-independent-review: the record has no `stages` list, so no review is recorded."]
    stages = [s for s in stages if isinstance(s, str)]
    if "review" not in stages:
        return ["skipped-independent-review: `stages` has no `review`; run the reviewer on the whole diff."]
    last_review = len(stages) - 1 - stages[::-1].index("review")
    changed_after = [s for s in stages[last_review + 1:] if s in CHANGE_STAGES]
    if changed_after:
        return [f"skipped-independent-review: `{changed_after[0]}` ran after the last `review`, "
                "so the final diff was not reviewed; review it again."]
    return []


def approval_time(value) -> datetime | None:
    """The approval as an aware datetime; None for ``n/a``. Raises ValueError otherwise."""
    if isinstance(value, str) and value.strip().lower() == "n/a":
        return None
    if not isinstance(value, str) or "T" not in value:
        raise ValueError
    when = datetime.fromisoformat(value.strip())
    if when.tzinfo is None:
        raise ValueError
    return when


def approval_failures(rec: dict, required: bool, repo: str | None, base: str | None,
                      trunk: str | None = None) -> list[str]:
    """Record-level approval failures, then (with a base) commits authored before the approval.
    Raises CannotCheck when the commits cannot be read."""
    if "plan_approved" not in rec:
        return ["skipped-plan-approval: the record has no `plan_approved`; write the time of "
                f"{HUMAN_APPROVAL} (`date -Iseconds`), or `n/a` when approval was not required."]
    try:
        when = approval_time(rec["plan_approved"])
    except ValueError:
        return [f"skipped-plan-approval: `plan_approved: {rec['plan_approved']}` is neither `n/a` nor an "
                "ISO 8601 date-time with a UTC offset (`date -Iseconds`)."]
    if when is None:
        if required:
            return ["skipped-plan-approval: approval was required but `plan_approved` is `n/a`; "
                    f"implementation needs {HUMAN_APPROVAL}."]
        return []
    if base is None:
        return []
    early = [sha[:12] for sha, at in run_commits(repo or ".", base, trunk) if at < when]
    if early:
        return [f"skipped-plan-approval: commits authored before the plan was approved "
                f"({rec['plan_approved']}): {', '.join(early)}. Rerunning cannot fix this; report it."]
    return []


def check(args) -> int:
    try:
        rec = parse_yaml_lite(Path(args.record).read_text(encoding="utf-8"))
        if not isinstance(rec, dict):
            raise YamlLiteError("not a mapping")
    except (OSError, UnicodeDecodeError, YamlLiteError) as e:
        print(f"record_gate: cannot check: cannot read {args.record}: {e}", file=sys.stderr)
        return 2

    outcome = rec.get("outcome")
    if outcome in NOT_DONE:
        print(f"record_gate: outcome is {outcome}, not a done report; gates not applied.")
        return 0

    repo = args.repo or "."
    base = args.base or (str(rec["base"]) if rec.get("base") is not None else None)
    trunk = args.trunk or (str(rec["trunk"]) if rec.get("trunk") is not None else None)
    review, approval, cannot = [], [], []

    if rec.get("reviewed_diff") is not None:
        if base is None:
            cannot.append("`reviewed_diff` needs `base` (in the record or --base) to recompute.")
        else:
            try:
                if fingerprint(repo, base) != str(rec["reviewed_diff"]).strip():
                    review.append("skipped-independent-review: the change has changed since the review "
                                  "(`reviewed_diff` no longer matches); review the final diff again.")
            except CannotCheck as e:
                cannot.append(str(e))
    else:
        review = review_failures(rec)

    try:
        approval = approval_failures(rec, args.require_plan_approval, repo, base, trunk)
    except CannotCheck as e:
        cannot.append(str(e))

    for f in approval + review:
        print(f"record_gate: FAIL {f}", file=sys.stderr)
    for c in cannot:
        print(f"record_gate: cannot check: {c}", file=sys.stderr)
    if approval:
        print("record_gate: not done: stop and report the skipped plan approval to the human.", file=sys.stderr)
        return 3
    if cannot:
        print("record_gate: not done: the record could not be checked; report why, do not loop.", file=sys.stderr)
        return 2
    if review:
        print("record_gate: not done: review the final diff if rounds remain, else stop and report.",
              file=sys.stderr)
        return 1
    print("record_gate: pass")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a run record before reporting done.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fp = sub.add_parser("fingerprint", help="print the fingerprint of the change since --base")
    fp.add_argument("--repo", default=".", help="repository (default: current directory)")
    fp.add_argument("--base", required=True, help="the commit the run started from")
    ck = sub.add_parser("check", help="check a run record")
    ck.add_argument("record", help="path to the run record (.claude/runs/*.yml)")
    ck.add_argument("--require-plan-approval", action="store_true",
                    help="approval was required for this run, so `plan_approved: n/a` fails")
    ck.add_argument("--repo", help="repository (default: current directory)")
    ck.add_argument("--base", help="overrides the record's `base`: the commit the run started from")
    ck.add_argument("--trunk", help="overrides the record's `trunk`: commits reachable from it are not the run's")
    args = ap.parse_args(argv)
    if args.cmd == "fingerprint":
        try:
            print(fingerprint(args.repo, args.base))
        except CannotCheck as e:
            print(f"record_gate: cannot check: {e}", file=sys.stderr)
            return 2
        return 0
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
