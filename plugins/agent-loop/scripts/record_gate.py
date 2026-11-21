#!/usr/bin/env python3
"""Check a run record before the lead reports done.

Two gates from docs/categories.md, checked mechanically (docs/DESIGN.md,
"Gates"):

- ``skipped-independent-review``: ``stages`` lists a ``review`` after the last
  stage that changed the diff (``implement`` or ``test-write``), so the final
  diff was reviewed.
- ``skipped-plan-approval``: ``plan_approved`` is the time the human approved
  the plan (ISO 8601 with a UTC offset) or ``n/a`` when no approval was
  required; ``--require-plan-approval`` refuses ``n/a``. With ``--base`` it
  also refuses any commit in ``<base>..HEAD`` authored before that time.

Records whose ``outcome`` is ``in-progress`` or ``abandoned`` are not done
reports and are not gated.

Exit codes: 0 pass, 1 a gate failed (each failure printed to stderr), 2 the
record or the repository could not be read. Standard library only; reads the
record with retro_mine's YAML subset parser. Never writes anything.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retro_mine import YamlLiteError, parse_yaml_lite  # noqa: E402

CHANGE_STAGES = ("implement", "test-write")
NOT_DONE = ("in-progress", "abandoned")


class UsageError(Exception):
    pass


def review_failures(rec: dict) -> list[str]:
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


def commits_before(repo: str, base: str, when: datetime) -> list[str]:
    """Short hashes of commits in ``base..HEAD`` authored before ``when``."""
    if not base or base.startswith("-"):
        raise UsageError(f"--base must be a revision, not an option: {base!r}")
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", "--format=%h %aI", "--end-of-options", f"{base}..HEAD"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise UsageError(f"cannot run git: {e}") from None
    if out.returncode != 0:
        raise UsageError(f"git log {base}..HEAD failed: {out.stderr.strip()[:200]}")
    early = []
    for line in out.stdout.splitlines():
        sha, _, stamp = line.partition(" ")
        if datetime.fromisoformat(stamp) < when:
            early.append(sha)
    return early


def approval_failures(rec: dict, required: bool, repo: str | None, base: str | None) -> list[str]:
    if "plan_approved" not in rec:
        return ["skipped-plan-approval: the record has no `plan_approved`; write the time the human "
                "approved the plan (`date -Iseconds`), or `n/a` when approval was not required."]
    try:
        when = approval_time(rec["plan_approved"])
    except ValueError:
        return [f"skipped-plan-approval: `plan_approved: {rec['plan_approved']}` is neither `n/a` nor an "
                "ISO 8601 date-time with a UTC offset (`date -Iseconds`)."]
    if when is None:
        if required:
            return ["skipped-plan-approval: approval was required but `plan_approved` is `n/a`; "
                    "show the plan and wait for the human's approval."]
        return []
    if base is not None:
        early = commits_before(repo or ".", base, when)
        if early:
            return [f"skipped-plan-approval: commits authored before the plan was approved "
                    f"({rec['plan_approved']}): {', '.join(early)}."]
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a run record before reporting done.")
    ap.add_argument("record", help="path to the run record (.claude/runs/*.yml)")
    ap.add_argument("--require-plan-approval", action="store_true",
                    help="approval was required for this run, so `plan_approved: n/a` fails")
    ap.add_argument("--repo", help="repository to check commits in (default: current directory)")
    ap.add_argument("--base", help="the commit the run started from; commits in <base>..HEAD "
                    "authored before plan_approved fail")
    args = ap.parse_args(argv)
    if args.repo is not None and args.base is None:
        ap.error("--repo needs --base")

    try:
        rec = parse_yaml_lite(Path(args.record).read_text(encoding="utf-8"))
        if not isinstance(rec, dict):
            raise YamlLiteError("not a mapping")
    except (OSError, UnicodeDecodeError, YamlLiteError) as e:
        print(f"record_gate: cannot read {args.record}: {e}", file=sys.stderr)
        return 2

    outcome = rec.get("outcome")
    if outcome in NOT_DONE:
        print(f"record_gate: outcome is {outcome}, not a done report; gates not applied.")
        return 0

    try:
        failures = review_failures(rec) + approval_failures(
            rec, args.require_plan_approval, args.repo, args.base)
    except UsageError as e:
        print(f"record_gate: {e}", file=sys.stderr)
        return 2
    for f in failures:
        print(f"record_gate: FAIL {f}", file=sys.stderr)
    if failures:
        print("record_gate: not done: fix the cause and rerun, or report the run as not done "
              "(outcome: in-progress).", file=sys.stderr)
        return 1
    print("record_gate: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
