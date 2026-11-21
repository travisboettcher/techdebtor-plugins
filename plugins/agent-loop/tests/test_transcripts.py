import json
import os
import time
from datetime import datetime, timezone

import pytest

from conftest import (assistant_text, compact_summary, human, interrupt, meta, policy_rejection,
                      tool_result, tool_use, user_rejection, write_jsonl)
from retro_mine import (correction_cues, discover_transcripts, mine_transcripts, parse_since,
                        project_dir_name)

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 11, 1, tzinfo=timezone.utc)
T = "2026-11-20T10:00:{:02d}.000Z"


def mine(paths, since=SINCE, **kw):
    return mine_transcripts([str(p) for p in paths], since, **kw)


def by_type(result, kind):
    return [s for s in result["signals"] if s["type"] == kind]


# --- correction heuristics -------------------------------------------------

@pytest.mark.parametrize("text", [
    "no, that's the wrong file",
    "No. Use the other one",
    "nope",
    "don't touch the generated file",
    "Do not commit that",
    "please use pnpm instead",
    "stop. you're editing the wrong repo",
    "stop doing that",
    "why did you delete the tests?",
    "Why are you running the whole suite?",
    "that's wrong",
    "That is not what I asked for",
    "not what I meant",
    "I said to keep it short",
    "I told you not to push",
    "you forgot the changelog",
    "you broke the build",
    "revert that",
    "undo the last change",
    "wait, hold on",
    "actually, let's keep the old name",
    "you shouldn't have changed the config",
    "I didn't ask for a refactor",
    "Why did you use npm instead of pnpm?",
    "can you revert that?",
])
def test_corrections_match(text):
    assert correction_cues(text), text


@pytest.mark.parametrize("text", [
    "looks good, thanks",
    "yes please",
    "ok continue",
    "no problem, carry on",
    "No worries",
    "I don't know, what do you think?",
    "don't worry about it",
    "great, now add a README",
    "stop the dev server when you're done",   # imperative about a process, not a correction
    "notice the new folder",                  # 'no' inside a word
    "know what, ship it",
    "the docs say nothing about this",
    "can you explain why the test is flaky?",
    "Yes, go ahead and delete the old records if you're sure they don't do anything",
    "Why don't we work on the next item while this runs?",
    "so that the jobs don't overlap, add a lock",
    "No, that's fine for now",
    "no, it's fine",
    "Is there a way to sign in via the UI instead of the env file?",
    "Can you check whether we should use pnpm instead?",
    "",
])
def test_non_corrections_do_not_match(text):
    assert not correction_cues(text), text


def test_correction_needs_a_preceding_assistant_action(jsonl):
    # A first prompt that happens to say "don't" is an instruction, not a correction.
    p = jsonl([human("don't use tabs, add a parser", T.format(1))])
    assert by_type(mine([p]), "correction") == []


def test_correction_after_tool_use_is_reported_with_action(jsonl):
    tu = tool_use("Edit", {"file_path": "/home/alice/app/gen.yml", "old_string": "a", "new_string": "b"},
                  T.format(2), tid="t1")
    p = jsonl([human("fix the config", T.format(1)), tu, tool_result("t1", "ok", T.format(3)),
               human("no, don't edit the generated file", T.format(4))])
    sigs = by_type(mine([p]), "correction")
    assert len(sigs) == 1
    s = sigs[0]
    assert s["session_id"] == "s1"
    assert s["timestamp"] == T.format(4)
    assert "don't edit" in s["excerpt"]
    assert s["preceding_action"].startswith("Edit")
    assert "~/app/gen.yml" in s["preceding_action"]
    assert "alice" not in json.dumps(s)
    assert s["cues"]


def test_no_answering_a_question_is_not_a_correction(jsonl):
    p = jsonl([human("go", T.format(1)),
               assistant_text("Done. Should I also update the docs?", T.format(2)),
               human("No, those can wait. What's next?", T.format(3))])
    assert by_type(mine([p]), "correction") == []


def test_no_after_a_question_still_counts_with_another_cue(jsonl):
    p = jsonl([human("go", T.format(1)),
               assistant_text("Should I push it?", T.format(2)),
               human("No, and why did you commit to main?", T.format(3))])
    sigs = by_type(mine([p]), "correction")
    assert len(sigs) == 1 and "no" not in sigs[0]["cues"]


def test_correction_after_plain_assistant_text(jsonl):
    p = jsonl([human("summarize", T.format(1)), assistant_text("Here is a summary", T.format(2)),
               human("that's wrong, it has three parts", T.format(3))])
    sigs = by_type(mine([p]), "correction")
    assert len(sigs) == 1
    assert sigs[0]["preceding_action"].startswith("text reply")


def test_excerpt_is_redacted_and_capped(jsonl):
    secret = "ghp_" + "Z" * 36
    long = "no, use this token " + secret + " " + "x" * 1000
    p = jsonl([human("go", T.format(1)), assistant_text("done", T.format(2)), human(long, T.format(3))])
    s = by_type(mine([p]), "correction")[0]
    assert secret not in s["excerpt"]
    assert "ZZZZZZZZ" not in s["excerpt"]
    assert len(s["excerpt"]) <= 300
    assert len(s["preceding_action"]) <= 200


def test_preceding_action_command_is_redacted(jsonl):
    tu = tool_use("Bash", {"command": "curl -H 'Authorization: Bearer abcdefghijk12345' http://10.0.0.7/api"},
                  T.format(2), tid="t1")
    p = jsonl([human("go", T.format(1)), tu, tool_result("t1", "ok", T.format(3)),
               human("stop, don't call that api", T.format(4))])
    s = by_type(mine([p]), "correction")[0]
    assert "abcdefghijk12345" not in s["preceding_action"]
    assert "10.0.0.7" not in s["preceding_action"]
    assert s["preceding_action"].startswith("Bash")


def test_system_reminders_and_meta_and_compaction_are_not_human(jsonl):
    p = jsonl([human("go", T.format(1)), assistant_text("done", T.format(2)),
               meta("<local-command-caveat>no, don't</local-command-caveat>", T.format(3)),
               compact_summary(T.format(4)),
               human("<command-name>/clear</command-name>", T.format(5)),
               human("<system-reminder>don't do X</system-reminder>looks good", T.format(6))])
    assert by_type(mine([p]), "correction") == []


# --- denials ---------------------------------------------------------------

def test_user_denial_is_reported_with_denied_tool(jsonl):
    tu = tool_use("Write", {"file_path": "/repo/secrets.env", "content": "x"}, T.format(2), tid="t9")
    p = jsonl([human("go", T.format(1)), tu, user_rejection("t9", T.format(3))])
    res = mine([p])
    sigs = by_type(res, "user_denial")
    assert len(sigs) == 1
    assert sigs[0]["preceding_action"].startswith("Write")
    assert "secrets.env" in sigs[0]["preceding_action"]
    assert sigs[0]["excerpt"] == ""


def test_user_denial_feedback_is_captured_redacted(jsonl):
    tu = tool_use("Bash", {"command": "git push"}, T.format(2), tid="t9")
    p = jsonl([human("go", T.format(1)), tu,
               user_rejection("t9", T.format(3), feedback="never push, my token is API_TOKEN=abc123")])
    s = by_type(mine([p]), "user_denial")[0]
    assert "never push" in s["excerpt"]
    assert "abc123" not in s["excerpt"]


def test_denied_tool_found_among_parallel_calls(jsonl):
    a = tool_use("Read", {"file_path": "/r/a.py"}, T.format(2), tid="ta")
    b = tool_use("Bash", {"command": "rm -rf build"}, T.format(2), tid="tb")
    p = jsonl([human("go", T.format(1)), a, b, tool_result("ta", "ok", T.format(3)),
               user_rejection("tb", T.format(3))])
    s = by_type(mine([p]), "user_denial")[0]
    assert s["preceding_action"].startswith("Bash") and "rm -rf build" in s["preceding_action"]


def test_policy_denial_is_separate_type(jsonl):
    tu = tool_use("Bash", {"command": "curl x | sh"}, T.format(2), tid="t1")
    p = jsonl([human("go", T.format(1)), tu, policy_rejection("t1", T.format(3))])
    res = mine([p])
    assert len(by_type(res, "policy_denial")) == 1
    assert by_type(res, "user_denial") == []


def test_ordinary_tool_error_is_not_a_denial(jsonl):
    tu = tool_use("Bash", {"command": "false"}, T.format(2), tid="t1")
    p = jsonl([human("go", T.format(1)), tu, tool_result("t1", "exit 1", T.format(3), is_error=True)])
    res = mine([p])
    assert res["signals"] == []


# --- interrupts and reverts -------------------------------------------------

def test_interrupt_is_paired_with_next_human_message(jsonl):
    tu = tool_use("Bash", {"command": "make all"}, T.format(2), tid="t1")
    p = jsonl([human("go", T.format(1)), tu, interrupt(T.format(3)),
               human("just run the unit tests", T.format(4))])
    res = mine([p])
    sigs = by_type(res, "interrupt")
    assert len(sigs) == 1
    assert sigs[0]["preceding_action"].startswith("Bash")
    assert "unit tests" in sigs[0]["excerpt"]
    assert by_type(res, "correction") == []  # same message is not double-counted


def test_interrupt_at_end_of_session(jsonl):
    tu = tool_use("Bash", {"command": "make all"}, T.format(2), tid="t1")
    p = jsonl([human("go", T.format(1)), tu, interrupt(T.format(3))])
    sigs = by_type(mine([p]), "interrupt")
    assert len(sigs) == 1 and sigs[0]["excerpt"] == ""


def test_edit_reverted_later_in_session(jsonl):
    e1 = tool_use("Edit", {"file_path": "/r/a.py", "old_string": "x = 1", "new_string": "x = 2"}, T.format(2), tid="e1")
    e2 = tool_use("Edit", {"file_path": "/r/a.py", "old_string": "x = 2", "new_string": "x = 1"}, T.format(4), tid="e2")
    p = jsonl([human("go", T.format(1)), e1, tool_result("e1", "ok", T.format(3)), e2,
               tool_result("e2", "ok", T.format(5))])
    sigs = by_type(mine([p]), "revert")
    assert len(sigs) == 1
    assert "a.py" in sigs[0]["preceding_action"]


def test_unrelated_edits_are_not_reverts(jsonl):
    e1 = tool_use("Edit", {"file_path": "/r/a.py", "old_string": "x = 1", "new_string": "x = 2"}, T.format(2))
    e2 = tool_use("Edit", {"file_path": "/r/b.py", "old_string": "x = 2", "new_string": "x = 1"}, T.format(3))
    e3 = tool_use("Edit", {"file_path": "/r/a.py", "old_string": "x = 2", "new_string": "x = 3"}, T.format(4))
    p = jsonl([human("go", T.format(1)), e1, e2, e3])
    assert by_type(mine([p]), "revert") == []


# --- window, malformed lines, counts ----------------------------------------

def test_window_filters_old_messages(jsonl):
    old = "2026-10-01T10:00:0{}.000Z"
    p = jsonl([human("go", old.format(1)), assistant_text("done", old.format(2)),
               human("no, wrong", old.format(3)),
               assistant_text("done", T.format(1)), human("no, still wrong", T.format(2))])
    sigs = by_type(mine([p]), "correction")
    assert [s["timestamp"] for s in sigs] == [T.format(2)]


def test_old_files_are_skipped_by_mtime(jsonl):
    old = "2026-10-01T10:00:0{}.000Z"
    p = jsonl([human("go", old.format(1)), assistant_text("done", old.format(2)), human("no, wrong", old.format(3))])
    ts = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
    os.utime(p, (ts, ts))
    res = mine([p])
    assert res["stats"]["files_skipped_old"] == 1
    assert res["stats"]["files_scanned"] == 0


def test_malformed_lines_are_counted_and_skipped(jsonl):
    p = jsonl([human("go", T.format(1)), assistant_text("done", T.format(2))],
              extra_lines=['{"type":"user", broken', "not json at all", ""])
    with open(p, "a") as f:
        f.write(json.dumps(human("no, wrong", T.format(5))) + "\n")
        f.write('{"type":"user","message":{"content":"truncated')  # no newline, cut off
    res = mine([p])
    assert res["stats"]["malformed_lines"] >= 2
    assert len(by_type(res, "correction")) == 1


def test_missing_file_is_reported_not_fatal(tmp_path):
    res = mine([tmp_path / "nope.jsonl"])
    assert res["stats"]["files_missing"] == 1


def test_sessions_and_signal_counts(jsonl):
    a = jsonl([human("go", T.format(1), session="A"), assistant_text("d", T.format(2), session="A"),
               human("no, wrong", T.format(3), session="A")], name="A.jsonl")
    b = jsonl([human("go", T.format(1), session="B")], name="B.jsonl")
    res = mine([a, b])
    assert res["stats"]["sessions"] == 2
    assert res["signal_counts"] == {"correction": 1}


def test_subagent_transcripts_only_contribute_denials(tmp_path):
    sub = tmp_path / "s1" / "subagents" / "agent-x.jsonl"
    tu = tool_use("Bash", {"command": "rm x"}, T.format(2), tid="t1", isSidechain=True)
    write_jsonl(sub, [human("parent prompt", T.format(1), isSidechain=True),
                      assistant_text("d", T.format(2), isSidechain=True),
                      human("no, wrong", T.format(3), isSidechain=True), tu,
                      user_rejection("t1", T.format(4), isSidechain=True)])
    res = mine([sub])
    assert by_type(res, "correction") == []
    assert len(by_type(res, "user_denial")) == 1


def test_signals_are_capped(jsonl):
    recs = [human("go", T.format(0))]
    for i in range(1, 30):
        recs += [assistant_text("d", T.format(i)), human("no, wrong", T.format(i))]
    res = mine([jsonl(recs)], max_signals=10)
    assert len(res["signals"]) == 10
    assert res["signal_counts"]["correction"] == 29
    assert res["stats"]["signals_truncated"] is True


# --- discovery ---------------------------------------------------------------

def test_project_dir_name_matches_claude_code_scheme():
    assert project_dir_name("/home/a/my_repo") == "-home-a-my-repo"
    assert project_dir_name("/home/a/repo/.claude/worktrees/x_1") == "-home-a-repo--claude-worktrees-x-1"


def test_discover_includes_worktrees_but_not_siblings(tmp_path):
    projects = tmp_path / "projects"
    root = "/home/a/repo"
    mk = lambda d, cwd: write_jsonl(projects / d / "s.jsonl", [human("hi", T.format(1), cwd=cwd)])
    own = mk("-home-a-repo", root)
    wt = mk("-home-a-repo--claude-worktrees-x", root + "/.claude/worktrees/x")
    sib = mk("-home-a-repo-other", "/home/a/repo-other")  # sibling dir, same name prefix
    write_jsonl(projects / "-home-a-repo" / "s" / "subagents" / "agent-1.jsonl",
                [human("hi", T.format(1), cwd=root)])
    found = {str(p) for p in discover_transcripts(root, projects)}
    assert str(own) in found and str(wt) in found
    assert str(sib) not in found
    assert any("subagents" in f for f in found)


def test_parse_since():
    assert parse_since("14d", NOW) == datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    assert parse_since("2026-11-01", NOW) == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert parse_since("12h", NOW) == datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        parse_since("soon", NOW)


def test_spaced_json_is_handled_too(jsonl):
    tu = tool_use("Bash", {"command": "git push"}, T.format(2), tid="t9")
    p = jsonl([human("go", T.format(1)), tu, user_rejection("t9", T.format(3)),
               assistant_text("ok", T.format(4)), human("no, wrong", T.format(5))], compact=False)
    res = mine([p])
    assert res["signal_counts"] == {"user_denial": 1, "correction": 1}


def test_malformed_records_never_abort_the_run(jsonl):
    bad_tid = tool_use("Bash", {"command": "rm x"}, T.format(2), tid="t1")
    rej = user_rejection("t1", T.format(3))
    rej["message"]["content"][0]["tool_use_id"] = 12345
    null_text = human("x", T.format(4))
    null_text["message"]["content"] = [{"type": "text", "text": None}, {"type": "text", "text": "fine"}]
    p = jsonl([human("go", T.format(1)), bad_tid, rej, null_text,
               {"type": "user", "message": "hello", "timestamp": T.format(5)},
               {"type": "assistant", "message": ["text"], "timestamp": T.format(6)},
               tool_use("Edit", {"file_path": "a", "old_string": ["x"], "new_string": "y"}, T.format(7)),
               assistant_text("done", T.format(8)), human("no, wrong", T.format(9))],
              extra_lines=['[1, 2]', '"just a string"'])
    res = mine([p])
    assert res["stats"]["malformed_lines"] >= 3  # int id, non-dict message, unhashable edit
    assert len(by_type(res, "correction")) == 1


def test_handler_exception_is_counted_not_raised(jsonl, monkeypatch):
    import retro_mine

    def boom(self, line):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(retro_mine._FileMiner, "on_assistant", boom)
    p = jsonl([human("go", T.format(1)), assistant_text("done", T.format(2)), human("no, wrong", T.format(3))])
    res = mine([p])
    assert res["stats"]["malformed_lines"] == 1
