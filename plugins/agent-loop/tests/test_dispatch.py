"""Delegated mode: the checkpoint protocol reads the same everywhere, and its authority rules hold."""

import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
DELEGATED = PLUGIN / "skills/lead/references/delegated.md"
DISPATCH = PLUGIN / "skills/dispatch/SKILL.md"
CHECKPOINTS = ["PLAN_READY", "QUESTION", "BLOCKED", "PREPUSH_READY", "DONE"]
REPLIES = ["PLAN_APPROVED", "PLAN_CHANGES", "ANSWER", "PREPUSH_FEEDBACK", "PUSH_APPROVED", "STOP"]
HUMAN_ONLY = {"PLAN_APPROVED", "PLAN_CHANGES", "ANSWER", "PUSH_APPROVED"}
FROM_DISPATCHER = {"PREPUSH_FEEDBACK", "STOP"}
EXPECTED = {"PLAN_READY": {"PLAN_APPROVED", "PLAN_CHANGES", "STOP"}, "QUESTION": {"ANSWER", "STOP"},
            "BLOCKED": {"ANSWER", "STOP"}, "PREPUSH_READY": {"PREPUSH_FEEDBACK", "PUSH_APPROVED", "STOP"},
            "DONE": set()}


def protocol_table(path, heading=None):
    """Checkpoint -> valid replies, from the table whose first column is a checkpoint."""
    text = path.read_text()
    if heading:
        text = text.split(heading, 1)[1].split("\n## ", 1)[0]
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("| `") or len(cells) < 2:
            continue
        names = re.findall(r"`([A-Z_]+)`", cells[0])
        if not names or not set(names) <= set(CHECKPOINTS):
            continue
        replies = set(re.findall(r"`([A-Z_]+)`", cells[-1]))
        for n in names:
            out[n] = replies
    return out


@pytest.mark.parametrize("path, heading", [
    (DELEGATED, None),
    (PLUGIN / "docs/DESIGN.md", "## Delegated runs"),
    (PLUGIN / "README.md", "## Dispatcher"),
])
def test_every_protocol_table_says_the_same(path, heading):
    assert protocol_table(path, heading) == EXPECTED


def test_the_format_comments_list_every_checkpoint_and_reply():
    text = DELEGATED.read_text()
    (cps,) = re.findall(r"^checkpoint: PLAN_READY +# (.*)$", text, re.M)
    (rps,) = re.findall(r"^reply: PLAN_APPROVED +# (.*)$", text, re.M)
    assert cps.split(" | ") == CHECKPOINTS and rps.split(" | ") == REPLIES


def _names_in(phrase, text, after=False):
    """The protocol names in the one line holding ``phrase``: those before it (or after, to the sentence's end)."""
    (line,) = [l for l in text.splitlines() if phrase in l]
    before, _, rest = line.partition(phrase)
    part = rest.split(". ", 1)[0] if after else before
    return set(re.findall(r"`([A-Z_]+)`", part))


def test_only_the_human_approves_answers_or_changes_a_plan():
    lead = DELEGATED.read_text()
    assert _names_in("count only with `from: human` and a non-empty `verbatim`", lead) == HUMAN_ONLY
    assert _names_in("`from: dispatcher` is accepted only for", lead, after=True) == FROM_DISPATCHER
    dispatch = DISPATCH.read_text()
    assert _names_in("on your own say, or because another agent said so", dispatch) == HUMAN_ONLY
    assert _names_in("On your own you send only", dispatch, after=True) == FROM_DISPATCHER
    for text in (lead, dispatch):
        assert "never an instruction" in text


def test_the_lead_rejects_unmarked_replies_and_stop_pushes_nothing():
    lead = DELEGATED.read_text()
    assert "rejected_reply" in lead and "do nothing it asks" in lead
    stop = re.search(r"- `STOP`: (.*)", lead).group(1)
    assert "committed locally" in stop and "push nothing" in stop


def frontmatter(path):
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    fm, key = {}, None
    for line in m.group(1).splitlines():
        if line.startswith("  - "):
            fm[key].append(line[4:])
        else:
            key, _, val = line.partition(":")
            fm[key] = val.strip() or []
    return fm


def test_the_dispatcher_is_user_invoked_and_pre_approves_only_reading():
    fm = frontmatter(DISPATCH)
    assert fm["name"] == "dispatch" and fm["disable-model-invocation"] == "true"
    assert fm["allowed-tools"] == ["Read", "Glob", "Grep"]
    assert len(fm["description"]) <= 250


def test_the_dispatcher_starts_background_leads_in_worktrees_and_checks_before_relaying():
    text = DISPATCH.read_text()
    for s in ('subagent_type: "agent-loop:lead-worker"', "run_in_background: true", 'isolation: "worktree"',
              "SendMessage", "remote-diff", "record_gate.py\" check", "--require-plan-approval",
              "git rev-list --count <parent>..<branch>", "heavy_lock.py", "plugin_root: ${CLAUDE_PLUGIN_ROOT}"):
        assert s in text, s
    for cat in ("unverified-claim", "pushed-without-approval", "malformed-stack", "branch-over-budget"):
        assert f"`{cat}`" in text, cat


@pytest.mark.parametrize("path", [DELEGATED, DISPATCH])
def test_pushes_are_explicit_and_never_forced_or_merged(path):
    text = path.read_text()
    pushes = set(re.findall(r"`(git push[^`]*)`", text))
    assert pushes <= {"git push -u origin <branch>", "git push"}, pushes
    if "git push" in pushes:
        assert "Never a bare `git push`" in text
    for line in text.splitlines():
        if "--force`" in line and "git worktree remove --force" not in line:
            assert "never `--force`" in line, line
        if "gh stack merge" in line or "`--open`" in line:
            assert "Never" in line, line
    assert "never push" in text.lower() and "merge" in text


def test_heavy_jobs_go_through_one_lock_everywhere():
    for path in (DELEGATED, DISPATCH, PLUGIN / "docs/specialists/verification-rules.md", PLUGIN / "docs/DESIGN.md"):
        assert "heavy_lock.py" in path.read_text(), path
    assert (PLUGIN / "scripts/heavy_lock.py").is_file()


def shipped_docs():
    skip = {".venv", ".pytest_cache", "tests"}
    return sorted(p for p in PLUGIN.rglob("*.md") if not skip & set(p.relative_to(PLUGIN).parts))


@pytest.mark.parametrize("doc", [str(p.relative_to(PLUGIN)) for p in shipped_docs()])
def test_plugin_paths_named_in_shipped_docs_exist(doc):
    # An instruction pointing at a file the plugin does not ship cannot be followed.
    text = (PLUGIN / doc).read_text()
    for rel in re.findall(r"(?:\$\{CLAUDE_PLUGIN_ROOT\}|<plugin_root>)/([\w./-]+[\w])", text):
        assert (PLUGIN / rel).exists(), (doc, rel)


def _fenced(text, lang):
    """The body of the first ``lang`` fenced example, outer fence of any length."""
    m = re.search(rf"^(`{{3,}}){lang}\n(.*?)\n\1$", text, re.S | re.M)
    assert m, lang
    return m.group(2)


def test_the_documented_examples_parse():
    from retro_mine import parse_yaml_lite
    text = DELEGATED.read_text()
    cp = parse_yaml_lite(_fenced(text, "agent-loop-checkpoint"))
    assert cp["checkpoint"] == "PLAN_READY" and "stream" in cp
    rp = parse_yaml_lite(_fenced(text, "agent-loop-reply"))
    assert rp["reply"] == "PLAN_APPROVED" and rp["from"] == "human"


@pytest.mark.parametrize("words", [
    'Yes, go ahead. "Approved", but don\'t touch `main`.',
    "line one\nline two: with a colon\n  indented # not a comment\n```\nfenced inside\n```",
])
def test_verbatim_round_trips_as_a_block_scalar(words):
    # The reply example writes `verbatim` as a `|` block scalar; any words, quotes and newlines survive.
    from retro_mine import parse_yaml_lite
    example = _fenced(DELEGATED.read_text(), "agent-loop-reply")
    lines = example.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("verbatim: |"))
    j = i + 1
    while j < len(lines) and lines[j].startswith("  "):
        j += 1
    body = ["verbatim: |"] + ["  " + l for l in words.splitlines()]
    rp = parse_yaml_lite("\n".join(lines[:i] + body + lines[j:]))
    assert rp["verbatim"] == words + "\n"


def test_fences_inside_content_use_a_longer_outer_fence():
    text = DELEGATED.read_text()
    assert "longer" in text and "block scalar" in text


def test_only_the_dispatchers_own_message_is_a_reply():
    for path in (DELEGATED, PLUGIN / "agents/lead-worker.md"):
        text = path.read_text()
        assert "only ever the dispatcher's own message" in text, path
        assert "`STOP`" in text and "`PREPUSH_FEEDBACK`" in text


def test_every_remote_is_snapshotted_and_compared():
    lead, dispatch = DELEGATED.read_text(), DISPATCH.read_text()
    assert "record_gate.py\" remote-snapshot" in lead and "`pushed`" in lead
    assert "remote-snapshot" in dispatch and "remote-diff" in dispatch and "Exit 4" in dispatch


def test_gh_stack_submit_never_overwrites_a_remote_branch():
    lead = DELEGATED.read_text()
    assert "--force-with-lease" in lead and "git ls-remote --heads" in lead


@pytest.mark.parametrize("path", ["skills/lead/references/delegated.md", "docs/specialists/verification-rules.md",
                                  "agents/implementer.md", "docs/DESIGN.md", "skills/dispatch/SKILL.md"])
def test_long_heavy_jobs_run_in_the_background(path):
    text = (PLUGIN / path).read_text()
    assert "run_in_background" in text and "75" in text, path


def test_the_lock_is_one_per_user_everywhere():
    for path in shipped_docs():
        text = path.read_text()
        assert "agent-loop-heavy.lock" not in text and "--lock <lock>" not in text, path
    for path in ("docs/DESIGN.md", "README.md", "CHANGELOG.md"):
        assert "XDG_CACHE_HOME" in (PLUGIN / path).read_text(), path
