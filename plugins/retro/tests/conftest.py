"""Builders for synthetic Claude Code transcripts (JSONL) and run records.

The shapes mirror what Claude Code writes: one JSON object per line, with
`type` user/assistant, `message.content` as a string (typed prompt) or a list
of blocks (text, tool_use, tool_result), and an ISO `timestamp`.
"""

import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

_ids = itertools.count(1)


def _base(kind, ts, session="s1", cwd="/work/proj", **extra):
    rec = {
        "type": kind,
        "uuid": f"u{next(_ids)}",
        "sessionId": session,
        "timestamp": ts,
        "cwd": cwd,
        "isSidechain": False,
    }
    rec.update(extra)
    return rec


def human(text, ts, **kw):
    return _base("user", ts, message={"role": "user", "content": text},
                 origin={"kind": "human"}, turnOrigin="human", **kw)


def assistant_text(text, ts, **kw):
    return _base("assistant", ts, message={"role": "assistant", "content": [{"type": "text", "text": text}]}, **kw)


def tool_use(name, inp, ts, tid=None, **kw):
    tid = tid or f"toolu_{next(_ids)}"
    return _base("assistant", ts, message={"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}, **kw)


def tool_result(tid, text, ts, is_error=False, **kw):
    return _base("user", ts, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": is_error}]}, **kw)


def user_rejection(tid, ts, feedback=None, **kw):
    text = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
            "(eg. if it was a file edit, the new_string was NOT written to the file). "
            "STOP what you are doing and wait for the user to tell you how to proceed.")
    if feedback:
        text = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
                "(eg. if it was a file edit, the new_string was NOT written to the file). "
                "To tell you how to proceed, the user said:\n" + feedback)
    rec = tool_result(tid, text, ts, is_error=True, **kw)
    rec["toolUseResult"] = "User rejected tool use"
    return rec


def policy_rejection(tid, ts, **kw):
    rec = tool_result(tid, "Permission for this action was denied by the auto mode classifier.", ts,
                      is_error=True, **kw)
    rec["permissionDecision"] = {"decision": "reject", "source": "config", "reasonType": "classifier"}
    return rec


def interrupt(ts, **kw):
    return _base("user", ts, message={"role": "user", "content": [
        {"type": "text", "text": "[Request interrupted by user for tool use]"}]}, **kw)


def compact_summary(ts, **kw):
    return _base("user", ts, message={"role": "user", "content":
                 "This session is being continued from a previous conversation that ran out of context. don't"},
                 isCompactSummary=True, turnOrigin="human", **kw)


def meta(text, ts, **kw):
    return _base("user", ts, message={"role": "user", "content": text}, isMeta=True, **kw)


def write_jsonl(path, records, extra_lines=(), compact=True):
    """Write records one per line. Claude Code writes compact JSON; compact=False
    writes `"key": "value"` spacing to check the miner does not depend on it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seps = (",", ":") if compact else (", ", ": ")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, separators=seps) + "\n")
        for line in extra_lines:
            f.write(line + "\n")
    return path


@pytest.fixture
def jsonl(tmp_path):
    def make(records, name="session.jsonl", extra_lines=(), compact=True):
        return write_jsonl(tmp_path / "transcripts" / name, records, extra_lines, compact)
    return make
