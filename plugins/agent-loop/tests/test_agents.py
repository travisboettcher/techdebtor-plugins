"""The agents: names, least-privilege tools, pools and the shared report formats."""

import json
import re
from pathlib import Path

import pytest

from retro_mine import DEFAULT_SELECTION, parse_yaml_lite

PLUGIN = Path(__file__).resolve().parent.parent
AGENTS = PLUGIN / "agents"
TABLE = parse_yaml_lite(DEFAULT_SELECTION.read_text())
SPECIALISTS = TABLE["specialists"]
COORDINATORS = {"tester": "tester", "reviewer": "reviewer"}  # agent -> the pool it coordinates
WRITERS = {"implementer", "test-writer"}


def agent(name):
    text = (AGENTS / f"{name}.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, name
    fm = {}
    for line in m.group(1).splitlines():
        key, _, val = line.partition(": ")
        fm[key] = val
    fm["tools"] = json.loads(fm["tools"])
    if fm["description"].startswith('"'):
        fm["description"] = json.loads(fm["description"])
    return fm, text[m.end():]


ALL = sorted(p.stem for p in AGENTS.glob("*.md"))


def test_every_agent_is_accounted_for():
    assert set(ALL) == set(SPECIALISTS) | set(COORDINATORS) | WRITERS


@pytest.mark.parametrize("name", ALL)
def test_agent_frontmatter(name):
    fm, body = agent(name)
    assert fm["name"] == name
    assert not name.startswith("verify-"), "the verify- prefix is a project's verify skills"
    assert fm["model"] == "inherit"
    # Descriptions are loaded into every session: keep them short.
    assert len(fm["description"]) <= 220, (name, len(fm["description"]))


@pytest.mark.parametrize("name", ALL)
def test_least_privilege_tools(name):
    tools = set(agent(name)[0]["tools"])
    if name in COORDINATORS:
        assert tools == {"Agent", "Read", "Glob", "Grep"}
    elif name in WRITERS:
        assert tools == {"Read", "Glob", "Grep", "Write", "Edit", "Bash"}
    else:
        # Specialists read and run; nothing but the implementer and test-writer writes the repo,
        # and no specialist starts agents, so the tree stays two levels deep.
        assert tools <= {"Read", "Glob", "Grep", "Bash"}, (name, tools)


@pytest.mark.parametrize("coordinator, pool", COORDINATORS.items())
def test_coordinators_start_exactly_their_pool(coordinator, pool):
    _, body = agent(coordinator)
    named = set(re.findall(r"`agent-loop:([a-z-]+)`", body))
    assert named == {n for n, s in SPECIALISTS.items() if s["pool"] == pool}
    assert "in parallel" in body and "same defect" in body


def test_the_tester_runs_heavy_specialists_one_at_a_time_within_the_budget():
    _, body = agent("tester")
    assert "one at a time, never two at once" in body
    for word in ("heavy_runs", "heavy_minutes", "opt-in", "budget", "report_only", "blocking"):
        assert word in body, word
    light = {n for n, s in SPECIALISTS.items() if s["pool"] == "tester" and s["weight"] == "light"}
    assert light == {"check-runner"} and "Light ones (`check-runner`)" in body


def test_review_specialists_are_all_light():
    assert {s["weight"] for s in SPECIALISTS.values() if s["pool"] == "reviewer"} == {"light"}


SHARED = {"tester": PLUGIN / "docs/specialists/verification-rules.md",
          "reviewer": PLUGIN / "docs/specialists/review-rules.md"}


@pytest.mark.parametrize("name", sorted(SPECIALISTS))
def test_specialists_point_to_their_pools_shared_rules(name):
    _, body = agent(name)
    pool = SPECIALISTS[name]["pool"]
    mine, other = SHARED[pool], SHARED["reviewer" if pool == "tester" else "tester"]
    assert str(mine.relative_to(PLUGIN)) in body and str(other.relative_to(PLUGIN)) not in body
    assert "## Rules\n" not in body and "## Report\n" not in body, "the shared file holds them"
    assert f"agent-loop:{pool}" in body


@pytest.mark.parametrize("pool", ["tester", "reviewer"])
def test_shared_rules_and_reports(pool):
    text = SHARED[pool].read_text()
    if pool == "tester":
        assert "## Verification report" in text and "PASS | FAIL | PRE-EXISTING | BLOCKED | UNVERIFIED" in text
        assert "Change nothing in the repository" in text and "Never install anything" in text
        assert "BLOCKED" in text and "`<base>`" in text and "bash -c" in text and "timeout" in text
    else:
        assert "## Review report" in text and "failure scenario:" in text and "location: <path>:<line>" in text
        assert "Read only" in text and "Escalate:" in text and "Focus section" in text
    assert "Specialist: <your name>" in text


@pytest.mark.parametrize("coordinator, pool", COORDINATORS.items())
def test_coordinators_pass_the_shared_rules_on(coordinator, pool):
    _, body = agent(coordinator)
    assert str(SHARED[pool].relative_to(PLUGIN)) in body and "the shared rules path" in body


def test_the_correctness_reviewer_sweeps_for_security_and_escalates():
    _, body = agent("correctness-reviewer")
    assert "Security sweep" in body and "`security-reviewer` under Escalate" in body
    _, coord = agent("reviewer")
    assert "escalat" in coord


def test_the_tester_never_starts_heavy_work_without_budget_and_blocking_wins():
    _, body = agent("tester")
    assert "0 or less" in body and "budget_max" in body
    assert "report-only only if every source was" in body and "[report-only]" in body


def test_the_moved_standing_checks_kept_their_text():
    # Regex timing moved from the tester to the fuzzer, the least-privilege check from the reviewer to the
    # permissions reviewer, the measurement checks to the measurement auditor, verify skills to the check runner.
    _, fuzzer = agent("fuzzer")
    assert "timeout 5" in fuzzer and '"ab.cd-" * 30000' in fuzzer and "`regex-performance`" in fuzzer
    _, perms = agent("permissions-reviewer")
    assert "`over-broad-pre-approval`" in perms and "--output=<file>" in perms and "*/scripts/x.py" in perms
    _, audit = agent("measurement-auditor")
    for cat in ("measurement-attribution-leak", "shared-state-false-failures", "wrong-auth-identity",
                "silent-allowlist", "new-check-not-opt-in"):
        assert f"`{cat}`" in audit, cat
    _, runner = agent("test-runner")
    assert "PRE-EXISTING" in runner and "check mode only" in runner


def test_specialist_categories_named_in_bodies_are_their_own_or_catalogued():
    catalog = set(re.findall(r"^\| `([a-z][a-z0-9]*(?:-[a-z0-9]+)+)` \|",
                             (PLUGIN / "docs/categories.md").read_text(), re.M))
    for name in SPECIALISTS:
        _, body = agent(name)
        named = set(re.findall(r"\(`([a-z]+(?:-[a-z]+)+)`", body)) - set(SPECIALISTS) - set(TABLE["tags"])
        assert named <= catalog, (name, named - catalog)
