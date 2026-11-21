#!/usr/bin/env python3
"""Mine run records, the rules ledger and Claude Code transcripts for /retro.

Standard library only (Python 3.11+). Prints one JSON document to stdout:

- ``signals``: places in session transcripts where the human corrected,
  interrupted or denied the agent, or where an edit was later undone. Each
  carries a short, redacted excerpt and a summary of the agent action before it.
- ``run_records`` / ``category_counts``: findings from ``.claude/runs/*.yml``
  in every worktree of the project (counts are scoped to ``--since``).
- ``ledgers``: every rule in the project and user rules ledgers, with the
  occurrences of its category in all run records since the rule was added.
- ``window``: the windows actually used. Transcript signals reach back past
  ``--since`` to the oldest ledger rule's ``added`` date, at most 90 days, so
  every rule can be verified against signals since it was added.

Nothing raw leaves this script: every string taken from a transcript or a
record passes through ``redact()`` first, and excerpts are capped.

Run records and ledgers are parsed with a small YAML-subset parser
(``parse_yaml_lite``) for the fixed shapes in docs/DESIGN.md (mappings,
lists, scalars, block scalars, empty flow lists). Parsing here, rather than
handing the files to the skill unparsed, is what lets the miner do the
counting (category counts, occurrences since ``added``) deterministically. A
file that does not parse is reported in ``parse_errors`` with its redacted
text, so the skill can still read it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1
EXCERPT_MAX = 300
ACTION_MAX = 200

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_KEYWORDS = r"(?:api[_-]?key|access[_-]?key|private[_-]?key|key|token|secret|passw(?:or)?d|passwd|pwd|passphrase|credentials?|cookie|session[_-]?id)"

# Token boundary: "_", "-" and other punctuation count as a boundary, unlike
# \b, so a secret glued to an identifier (host_10.0.0.5, x_ghp_...) is still
# found. Only a letter or digit directly before the match blocks it.
_B = r"(?<![A-Za-z0-9])"


def _mixed(prefix_len: int):
    """Redact a prefixed token only if its body looks random (has a digit or an
    upper-case letter), so prose like "pypi-packaging-guide" survives."""
    def sub(m: re.Match) -> str:
        body = m.group(0)[prefix_len:]
        return "[REDACTED:token]" if re.search(r"[0-9A-Z]", body) else m.group(0)
    return sub


def _keep_redacted(prefix_group: int, value_group: int, label: str = "secret"):
    def sub(m: re.Match) -> str:
        v = m.group(value_group)
        return m.group(prefix_group) + (v if v.startswith("[REDACTED") else f"[REDACTED:{label}]")
    return sub


def _user_cred(m: re.Match) -> str:
    v = m.group(2)
    if v.startswith("[REDACTED") or re.fullmatch(r"['\"]?\d+:\d+['\"]?", v):  # uid:gid, not a credential
        return m.group(0)
    return m.group(1) + "[REDACTED:cred]"


_VALUE = r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s'\",;&]+)"

_REDACTIONS: list[tuple[re.Pattern, object]] = [
    # PEM private key blocks (also a block cut off before its END line).
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:.*?-----END [A-Z0-9 ]*PRIVATE KEY-----|.*\Z)", re.S),
     "[REDACTED:private-key]"),
    # Home directories: keep the path shape, drop the user name.
    (re.compile(r"(?<![\w/])/(?:home|Users)/[^/\s'\"]+(?=/|\b)"), "~"),
    # Credentials embedded in URLs.
    (re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED:cred]@"),
    # Authorization headers, any scheme.
    (re.compile(r"(?i)\b((?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic|token|digest)\s+)?[^\s'\",;]+"),
     r"\1[REDACTED:auth]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}"), "Bearer [REDACTED:auth]"),
    # Known token shapes.
    (re.compile(_B + r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED:token]"),
    (re.compile(_B + r"gh[pousr]_[A-Za-z0-9]{16,}"), "[REDACTED:token]"),
    (re.compile(_B + r"sk-[A-Za-z0-9_-]{16,}"), "[REDACTED:token]"),
    (re.compile(_B + r"xox[a-z]-[A-Za-z0-9-]{10,}"), "[REDACTED:token]"),
    (re.compile(_B + r"gl(?:pat|ptt|dt|rt|cbt|soat|ft)-[A-Za-z0-9_-]{16,}"), "[REDACTED:token]"),
    (re.compile(_B + r"npm_[A-Za-z0-9]{16,}"), _mixed(4)),
    (re.compile(_B + r"pypi-[A-Za-z0-9_-]{16,}"), _mixed(5)),
    (re.compile(_B + r"hf_[A-Za-z0-9]{16,}"), _mixed(3)),
    (re.compile(_B + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"), "[REDACTED:token]"),
    (re.compile(_B + r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED:jwt]"),
    # Command-line credentials: curl -u user:pass, --password VALUE, mysql -pVALUE.
    (re.compile(r"(?<!\S)((?:-u|--user)(?:\s+|=))(['\"]?[^\s:'\"]+:[^\s'\"]+['\"]?)"), _user_cred),
    (re.compile(r"(?i)(?<!\S)(--(?:password|passwd|pass|token|secret|api-key|apikey|access-token|auth-token)"
                r"(?:\s+|=))" + _VALUE), _keep_redacted(1, 2)),
    (re.compile(r"\b((?:mysql|mysqldump|mysqladmin|mariadb|mariadb-dump|sshpass)\b[^\n|;&]*?\s-p\s*)" + _VALUE),
     _keep_redacted(1, 2)),
    # NAME_KEY=value, password: value, "token": "value" ... (value redacted, name kept).
    (re.compile(r"(?i)(\b[A-Za-z0-9_.-]*" + _KEYWORDS + r"[A-Za-z0-9_]*[\"']?\s*[=:]\s*)" + _VALUE),
     _keep_redacted(1, 2)),
    # Short password names, as whole words only (pw: x, pass = x).
    (re.compile(r"(?i)(" + _B + r"(?:pw|pass)[\"']?\s*[=:]\s*)" + _VALUE), _keep_redacted(1, 2)),
    # Emails.
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
    # IPv4 addresses, private or not (with optional CIDR / port), also glued to "_".
    (re.compile(r"(?<![0-9.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"
                r"(?:/\d{1,2})?(?::\d{1,5})?(?![0-9])"),
     "[REDACTED:ip]"),
    # Long hex runs (keys, hashes).
    (re.compile(_B + r"[0-9a-fA-F]{32,}(?![A-Za-z0-9])"), "[REDACTED:hex]"),
]

def _user_pattern(name: str | None) -> re.Pattern | None:
    """The local account name, redacted wherever it appears as a whole token
    (e.g. inside Claude Code's mangled project directory names)."""
    if not name or len(name) < 3 or name.lower() in ("root", "home", "user", "users", "admin"):
        return None
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])")


_LOCAL_USER = _user_pattern(os.path.basename(os.path.expanduser("~").rstrip("/")))

_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_-]{32,}={0,2}")


def _b64_sub(m: re.Match) -> str:
    s = m.group(0)
    if any(c.isdigit() for c in s) and any(c.isupper() for c in s) and any(c.islower() for c in s):
        return "[REDACTED:blob]"
    return s


def redact(text: str | None) -> str:
    """Replace anything secret-shaped in ``text``. When in doubt, redact."""
    if not text:
        return ""
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    if _LOCAL_USER is not None:
        text = _LOCAL_USER.sub("[user]", text)
    return _B64_RUN.sub(_b64_sub, text)


def _redact_tree(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [_redact_tree(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _redact_tree(v) for k, v in obj.items()}
    return obj


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    # Redact before clipping so a secret is never cut into an unrecognisable fragment.
    return _clip(redact(text[:4000]), limit)


# ---------------------------------------------------------------------------
# Correction heuristics
# ---------------------------------------------------------------------------

_CUES: list[tuple[str, re.Pattern]] = [
    ("no", re.compile(r"^\W*(?:no|nope|nah)\b(?!,?\s+(?:problem|worries|rush|thanks|thank you|(?:that|it)'?s (?:fine|ok|okay|good)|all good)\b)")),
    ("negation", re.compile(r"\b(?:never (?:do|use|touch|edit|push|commit|run|change|add|delete)\b|^\W*never\b)")),
    ("instead", re.compile(r"\binstead\b")),
    ("stop", re.compile(r"^\W*stop\b(?=\s*[.!,;:\-]|\s*$)|\bstop (?:doing|that|it|changing|editing|adding|using|trying|making|touching|creating|deleting)\b")),
    ("why-did-you", re.compile(r"\bwhy (?:did|are|would|do|were|have|is|was) you\b|\bwho (?:told|asked) you\b")),
    ("wrong", re.compile(r"^\W*wrong\b|\bthat'?s (?:wrong|not right|incorrect|not it|not what)\b|\bthat is (?:wrong|not right|not what|incorrect)\b|\b(?:is|was|looks|are) (?:still )?wrong\b")),
    ("not-what-i", re.compile(r"\bnot what i (?:asked|meant|wanted|said)\b")),
    ("i-said", re.compile(r"\bi (?:said|told you|already (?:said|told you|asked)|asked you|meant)\b")),
    ("you-did", re.compile(r"\byou (?:forgot|missed|broke|deleted|removed|ignored|skipped|overwrote|didn'?t)\b")),
    ("revert", re.compile(r"\b(?:revert|undo|roll ?back|put (?:it|that|them) back)\b")),
    ("wait", re.compile(r"^\W*(?:wait|hold on|hang on)\b")),
    ("actually", re.compile(r"^\W*actually\b")),
    ("should-not-have", re.compile(r"\b(?:shouldn'?t|should not) have\b|\byou were (?:supposed|meant) to\b|\bwhy not just\b")),
    ("didnt-ask", re.compile(r"\bi didn'?t (?:ask|want|say|mean)\b|\bdidn'?t ask (?:you|for)\b")),
]
# "don't" counts only as an imperative: at the start of a clause or after a
# softener ("please don't", "and don't"), not "they don't" / "why don't we".
_DONT = re.compile(r"(?:^|[.!?;:,\n-]\s*|\b(?:please|pls|and|but|so|just|you|then|also|now|again|still)\s+)"
                   r"(?:don'?t|do not)\b(?!\s+(?:worry|know|think|mind|care|see|understand|remember|have)\b)")


_WEAK_CUES = {"dont", "instead", "actually", "negation"}
_QUESTION = re.compile(r"\W*(?:is|are|can|could|would|will|should|does|do|did|how|what|which|where|when|is there|any)\b[^.!?\n]*\?")


def correction_cues(text: str) -> list[str]:
    """Names of the correction cues found near the start of a human message."""
    if not text:
        return []
    t = text.lower().replace("’", "'")[:300]
    cues = [name for name, rx in _CUES if rx.search(t)]
    if _DONT.search(t):
        cues.append("dont")
    if _QUESTION.match(t):
        # An enquiry ("is there a way to ... instead?") is not a redirect by itself.
        cues = [c for c in cues if c not in _WEAK_CUES]
    return cues


# ---------------------------------------------------------------------------
# Transcript discovery
# ---------------------------------------------------------------------------

def project_dir_name(root: str) -> str:
    """Claude Code stores a project's transcripts in ~/.claude/projects/<name>,
    where <name> is the absolute path with every non-alphanumeric char as '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", root)


_CWD_RX = re.compile(r'"cwd":\s*"((?:[^"\\]|\\.)*)"')
_SESSION_RX = re.compile(r'"sessionId":\s*"([^"]+)"')


def _file_cwd(path: Path, max_lines: int = 200) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                m = _CWD_RX.search(line)
                if m:
                    try:
                        return json.loads('"' + m.group(1) + '"')
                    except ValueError:
                        return m.group(1)
    except OSError:
        return None
    return None


def discover_transcripts(root: str, projects_dir) -> list[Path]:
    """Transcripts for ``root`` and anything under it (worktrees get their own
    directory whose name has the project's as a prefix). A same-prefix sibling
    such as /x/repo-other is excluded by checking each file's recorded cwd."""
    root = os.path.abspath(root).rstrip("/") or "/"
    projects_dir = Path(projects_dir)
    name = project_dir_name(root)
    if not projects_dir.is_dir():
        return []
    found = []
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or not (d.name == name or d.name.startswith(name + "-")):
            continue
        for f in sorted(d.rglob("*.jsonl")):
            cwd = _file_cwd(f)
            if cwd is None:
                ok = d.name == name
            else:
                ok = cwd == root or cwd.startswith(root + "/")
            if ok:
                found.append(f)
    return found


def parse_since(spec: str, now: datetime) -> datetime:
    """'30d', '12h', '2w' or an ISO date/datetime."""
    m = re.fullmatch(r"\s*(\d+)\s*([hdw])\s*", spec or "")
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[unit]
    try:
        dt = datetime.fromisoformat(spec.strip())
    except (ValueError, AttributeError):
        raise ValueError(f"cannot parse --since {spec!r}: use e.g. 30d, 12h, 2w or 2026-11-01")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_ts(ts) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Transcript mining
# ---------------------------------------------------------------------------

def _has(line: str, key: str, value: str) -> bool:
    return f'"{key}":"{value}"' in line or f'"{key}": "{value}"' in line


_NOT_HUMAN_PREFIXES = (
    "<command-name>", "<command-message>", "<command-args>", "<local-command", "<task-notification>",
    "<bash-input>", "<bash-stdout>", "<bash-stderr>", "<user-memory-input>", "Caveat:",
    "This session is being continued from a previous conversation",
)
_REMINDER_RX = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_INTERRUPT = "[Request interrupted by user"
_USER_REJECT_MARKERS = ("User rejected tool use", "doesn't want to proceed with this tool use")
_TARGET_KEYS = ("file_path", "notebook_path", "path", "command", "url", "pattern", "query",
                "skill", "subagent_type", "description")


def summarize_tool(block: dict) -> str:
    name = block.get("name") or "tool"
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    target = next((inp[k] for k in _TARGET_KEYS if isinstance(inp.get(k), str) and inp[k].strip()), "")
    return _clip(redact(f"{name}: {target}" if target else name), ACTION_MAX)


def _message(rec) -> dict:
    msg = rec.get("message")
    return msg if isinstance(msg, dict) else {}


def _text_of(block: dict) -> str:
    t = block.get("text")
    return t if isinstance(t, str) else ""


def _blocks(rec) -> list:
    content = _message(rec).get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _human_text(rec) -> str | None:
    """Text the human typed, or None if this user record is not a human turn."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return None
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    if rec.get("turnOrigin") not in (None, "human"):
        return None
    content = _message(rec).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(_text_of(b) for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    text = _REMINDER_RX.sub("", text).strip()
    if not text or text.startswith(_NOT_HUMAN_PREFIXES):
        return None
    return text


class _FileMiner:
    def __init__(self, path: Path, since: datetime, subagent: bool, stats: Counter, emit):
        self.path, self.since, self.subagent, self.stats, self.emit = path, since, subagent, stats, emit
        self.session = None
        self.last_action_raw = None        # raw line of the latest assistant tool_use/text
        self.tool_lines = deque(maxlen=32)  # raw assistant lines with tool_use, for denial lookup
        self.acted = False                  # assistant acted since the last human turn
        self.acted_tool = False             # ... and used a tool
        self.pending_interrupt = None
        self.edits: dict[str, list[tuple[int, int]]] = {}

    def _load(self, line):
        self.stats["parsed_lines"] += 1
        try:
            rec = json.loads(line)
        except ValueError:
            rec = None
        if not isinstance(rec, dict) or ("message" in rec and not isinstance(rec["message"], dict)):
            self.stats["malformed_lines"] += 1
            return None
        return rec

    def _in_window(self, rec) -> bool:
        ts = _parse_ts(rec.get("timestamp"))
        return ts is None or ts >= self.since

    def _signal(self, kind, rec, text, action, cues=()):
        self.emit({
            "type": kind,
            "session_id": rec.get("sessionId") or self.session or self.path.stem,
            "timestamp": rec.get("timestamp"),
            "excerpt": excerpt(text) if text else "",
            "preceding_action": action,
            "cues": list(cues),
            "source": "subagent" if self.subagent else "main",
        })

    def _action_summary(self) -> str:
        if not self.last_action_raw:
            return ""
        try:
            rec = json.loads(self.last_action_raw)
        except ValueError:
            return ""
        blocks = _blocks(rec)
        tools = [b for b in blocks if b.get("type") == "tool_use"]
        if tools:
            return summarize_tool(tools[-1])
        prev = ""
        for raw in reversed(self.tool_lines):
            try:
                t = [b for b in _blocks(json.loads(raw)) if b.get("type") == "tool_use"]
            except ValueError:
                continue
            if t:
                prev = summarize_tool(t[-1])
                break
        return _clip("text reply" + (f" after {prev}" if prev and self.acted_tool else ""), ACTION_MAX)

    def _asked_question(self) -> bool:
        """Did the agent's last text reply end by asking something?"""
        if not self.last_action_raw:
            return False
        try:
            blocks = _blocks(json.loads(self.last_action_raw))
        except ValueError:
            return False
        texts = [b.get("text") for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)]
        return bool(texts) and "?" in texts[-1].rstrip()[-300:]

    def _find_tool(self, tool_use_id) -> str:
        for raw in reversed(self.tool_lines):
            if tool_use_id and tool_use_id not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            for b in _blocks(rec):
                if b.get("type") == "tool_use" and b.get("id") == tool_use_id:
                    return summarize_tool(b)
        return "unknown tool"

    def on_tool_result(self, line):
        self.acted = True
        if not (any(m in line for m in _USER_REJECT_MARKERS) or _has(line, "decision", "reject")):
            return
        rec = self._load(line)
        if not rec or not self._in_window(rec):
            return
        user_rejected = rec.get("toolUseResult") == "User rejected tool use"
        decision = rec.get("permissionDecision")
        policy = isinstance(decision, dict) and decision.get("decision") == "reject"
        for b in _blocks(rec):
            if b.get("type") != "tool_result":
                continue
            content = b.get("content")
            if isinstance(content, list):
                content = "\n".join(_text_of(c) for c in content if isinstance(c, dict))
            content = content if isinstance(content, str) else ""
            tool_use_id = b.get("tool_use_id")
            if tool_use_id is not None and not isinstance(tool_use_id, str):
                self.stats["malformed_lines"] += 1
                continue
            action = self._find_tool(tool_use_id)
            if user_rejected or "doesn't want to proceed with this tool use" in content:
                _, sep, feedback = content.partition("the user said:")
                self._signal("user_denial", rec, feedback.strip() if sep else "", action)
            elif policy:
                self._signal("policy_denial", rec, "", action)

    def on_assistant(self, line):
        self.acted = True
        if _has(line, "type", "tool_use"):
            self.tool_lines.append(line)
            self.last_action_raw = line
            self.acted_tool = True
            if _has(line, "name", "Edit") or _has(line, "name", "MultiEdit"):
                self._check_revert(line)
        elif _has(line, "type", "text"):
            self.last_action_raw = line

    def _check_revert(self, line):
        rec = self._load(line)
        if not rec or not self._in_window(rec):
            return
        for b in _blocks(rec):
            if b.get("type") != "tool_use" or not isinstance(b.get("input"), dict):
                continue
            inp = b["input"]
            fp = inp.get("file_path")
            edits = inp.get("edits") if isinstance(inp.get("edits"), list) else [inp]
            for e in edits:
                if not isinstance(e, dict) or not isinstance(fp, str):
                    continue
                old, new = hash(e.get("old_string")), hash(e.get("new_string"))
                seen = self.edits.setdefault(fp, [])
                if (new, old) in seen:
                    self._signal("revert", rec, "", summarize_tool(b))
                    seen.remove((new, old))
                else:
                    seen.append((old, new))
                    del seen[:-50]

    def on_user(self, line):
        rec = self._load(line)
        if not rec or rec.get("type") != "user":
            return
        if self.subagent or rec.get("isSidechain"):
            return
        text = _human_text(rec)
        if text is None:
            return
        in_window = self._in_window(rec)
        if text.startswith(_INTERRUPT):
            self.pending_interrupt = (rec, self._action_summary()) if in_window else None
            self.acted = False
            return
        if self.pending_interrupt:
            prec, action = self.pending_interrupt
            self._signal("interrupt", prec, text, action, correction_cues(text))
            self.pending_interrupt = None
        elif self.acted and in_window:
            cues = correction_cues(text)
            if "no" in cues and self._asked_question():
                cues.remove("no")  # "no" answering the agent's question is not a correction
            if cues:
                self._signal("correction", rec, text, self._action_summary(), cues)
        self.acted = False
        self.acted_tool = False

    def _dispatch(self, line):
        if _has(line, "type", "tool_result"):
            self.on_tool_result(line)
        elif _has(line, "type", "assistant"):
            self.on_assistant(line)
        elif _has(line, "type", "user"):
            self.on_user(line)

    def run(self):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for line in f:
                self.stats["lines"] += 1
                if self.session is None:
                    m = _SESSION_RX.search(line)
                    if m:
                        self.session = m.group(1)
                try:
                    self._dispatch(line)
                except Exception:  # one odd record must never abort the run
                    self.stats["malformed_lines"] += 1
        if self.pending_interrupt:
            prec, action = self.pending_interrupt
            self._signal("interrupt", prec, "", action)
        return self.session


def mine_transcripts(paths, since: datetime, max_signals: int = 500) -> dict:
    stats = Counter()
    signals: list[dict] = []
    sessions = set()
    since_ts = since.timestamp()
    for p in paths:
        path = Path(p)
        try:
            st = path.stat()
        except OSError:
            stats["files_missing"] += 1
            continue
        if st.st_mtime < since_ts:
            stats["files_skipped_old"] += 1
            continue
        stats["files_scanned"] += 1
        stats["bytes"] += st.st_size
        subagent = "subagents" in path.parts
        try:
            session = _FileMiner(path, since, subagent, stats, signals.append).run()
        except OSError:
            stats["files_unreadable"] += 1
            continue
        if not subagent:
            sessions.add(session or path.stem)
    counts = Counter(s["type"] for s in signals)
    signals.sort(key=lambda s: s.get("timestamp") or "")
    truncated = len(signals) > max_signals
    if truncated:
        signals = signals[-max_signals:]
    out_stats = {k: stats.get(k, 0) for k in (
        "files_scanned", "files_skipped_old", "files_missing", "files_unreadable", "bytes", "lines", "parsed_lines", "malformed_lines")}
    out_stats["sessions"] = len(sessions)
    out_stats["signals_truncated"] = truncated
    return {"stats": out_stats, "signal_counts": dict(counts), "signals": signals}


# ---------------------------------------------------------------------------
# YAML subset (run records, ledger)
# ---------------------------------------------------------------------------

class YamlLiteError(ValueError):
    pass


def _outside_quotes(s: str, can_open):
    """Yield (index, char) for every character of ``s`` outside a quoted
    string. A quote opens only where ``can_open(s, i)`` allows it; inside double
    quotes a backslash escapes the next character, and inside single quotes
    ``''`` is a literal quote, as in YAML."""
    quote, i, n = None, 0, len(s)
    while i < n:
        c = s[i]
        if quote == '"':
            if c == "\\":
                i += 1
            elif c == '"':
                quote = None
        elif quote == "'":
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 1
                else:
                    quote = None
        elif c in "\"'" and can_open(s, i):
            quote = c
        else:
            yield i, c
        i += 1


def _strip_comment(s: str) -> str:
    for i, c in _outside_quotes(s, lambda s, i: i == 0 or s[i - 1] in " \t:-[,"):
        if c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _split_key(s: str):
    for i, c in _outside_quotes(s, lambda s, i: i == 0):
        if c == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            key = s[:i].strip()
            if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                key = _scalar(key)
            return key, s[i + 1:].strip()
    return None


def _split_flow(s: str) -> list[str]:
    parts, start = [], 0
    for i, c in _outside_quotes(s, lambda s, i: True):
        if c == ",":
            parts.append(s[start:i].strip())
            start = i + 1
    if s[start:].strip():
        parts.append(s[start:].strip())
    return parts


_YAML_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "\\": "\\", "/": "/", " ": " "}


def _unescape_double(body: str) -> str:
    try:
        return json.loads('"' + body + '"')
    except ValueError:
        # YAML allows escapes JSON does not (\x41, "\ "); unknown ones stay as written.
        return re.sub(r"\\(.)", lambda m: _YAML_ESCAPES.get(m.group(1), m.group(0)), body)


def _closing_quote(s: str) -> int:
    """Index of the quote that closes the string ``s`` opens at index 0, or -1."""
    q, i = s[0], 1
    while i < len(s):
        if q == '"' and s[i] == "\\":
            i += 2
            continue
        if s[i] == q:
            if q == "'" and i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return -1


def _scalar(s: str):
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s[0] in "\"'":
        end = _closing_quote(s)
        if end == -1:
            raise YamlLiteError(f"unterminated string: {s[:40]}")
        if end != len(s) - 1:
            raise YamlLiteError(f"text after closing quote: {s[:40]}")
        body = s[1:-1]
        return _unescape_double(body) if s[0] == '"' else body.replace("''", "'")
    if s.startswith("["):
        if not s.endswith("]"):
            raise YamlLiteError(f"unterminated flow list: {s[:40]}")
        return [_scalar(x) for x in _split_flow(s[1:-1])]
    if s.startswith("{"):
        if s == "{}":
            return {}
        raise YamlLiteError("flow mappings are not supported")
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?\d+\.\d+", s):
        return float(s)
    return s


class _YamlLite:
    def __init__(self, text: str):
        self.raw = text.splitlines()
        self.i = 0

    def _peek(self):
        """(indent, content) of the next meaningful line, skipping blanks/comments."""
        while self.i < len(self.raw):
            line = self.raw[self.i]
            if "\t" in line[: len(line) - len(line.lstrip())]:
                raise YamlLiteError(f"line {self.i + 1}: tab indentation")
            content = _strip_comment(line.strip()) if line.strip() else ""
            if content and content != "---":
                return len(line) - len(line.lstrip(" ")), content
            self.i += 1
        return None

    def parse(self):
        nxt = self._peek()
        if nxt is None:
            return None
        val = self._block(nxt[0])
        if self._peek() is not None:
            raise YamlLiteError(f"line {self.i + 1}: unexpected indentation or content")
        return val

    def _block(self, indent):
        _, content = self._peek()
        if content == "-" or content.startswith("- "):
            return self._seq(indent)
        return self._map(indent)

    def _value_after(self, indent, rest, allow_seq_same_indent):
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            return self._block_scalar(indent, rest)
        if rest:
            return _scalar(rest)
        nxt = self._peek()
        if nxt and (nxt[0] > indent or (allow_seq_same_indent and nxt[0] == indent
                                        and (nxt[1] == "-" or nxt[1].startswith("- ")))):
            return self._block(nxt[0])
        return None

    def _map(self, indent):
        out = {}
        while True:
            nxt = self._peek()
            if nxt is None or nxt[0] != indent or nxt[1] == "-" or nxt[1].startswith("- "):
                break
            kv = _split_key(nxt[1])
            if kv is None:
                raise YamlLiteError(f"line {self.i + 1}: expected 'key: value'")
            key, rest = kv
            self.i += 1
            out[key] = self._value_after(indent, rest, allow_seq_same_indent=True)
        return out

    def _seq(self, indent):
        out = []
        while True:
            nxt = self._peek()
            if nxt is None or nxt[0] != indent or not (nxt[1] == "-" or nxt[1].startswith("- ")):
                break
            body = nxt[1][1:]
            rest = body.lstrip(" ")
            if not rest:
                self.i += 1
                out.append(self._value_after(indent, "", allow_seq_same_indent=False))
            elif _split_key(rest) is not None and not rest.startswith(("\"", "'", "[")):
                # "- key: value" opens a mapping whose keys sit at this column.
                col = indent + 1 + (len(body) - len(rest))
                self.raw[self.i] = " " * col + rest
                out.append(self._map(col))
            else:
                self.i += 1
                out.append(_scalar(rest))
        return out

    def _block_scalar(self, indent, style):
        lines = []
        block_indent = None
        while self.i < len(self.raw):
            line = self.raw[self.i]
            if line.strip():
                ind = len(line) - len(line.lstrip(" "))
                if ind <= indent:
                    break
                if block_indent is None:
                    block_indent = ind
                lines.append(line[block_indent:] if ind >= block_indent else line.lstrip(" "))
            else:
                lines.append("")
            self.i += 1
        while lines and lines[-1] == "":
            lines.pop()
        if style.startswith("|"):
            text = "\n".join(lines)
        else:
            text, para = [], []
            for ln in lines:
                if ln == "":
                    text.append(" ".join(para))
                    para = []
                else:
                    para.append(ln.strip())
            text.append(" ".join(para))
            text = "\n".join(text)
        return text if style.endswith("-") or not text else text + "\n"


def parse_yaml_lite(text: str):
    """Parse the YAML subset used by run records and the rules ledger."""
    return _YamlLite(text).parse()


# ---------------------------------------------------------------------------
# Run records and ledgers
# ---------------------------------------------------------------------------

def _iso_date(value) -> str | None:
    """YYYY-MM-DD for a date-shaped value, None if it is not date-shaped.
    Raises ValueError for a date-shaped value that is not a real date (2026-02-30)."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        m = re.match(r"\d{4}-\d{2}-\d{2}", value.strip())
        if m:
            try:
                return date.fromisoformat(m.group(0)).isoformat()
            except ValueError:
                raise ValueError(f"invalid date: {m.group(0)}") from None
    return None


def _rec_date(rec, fname: str) -> str | None:
    """A record's date: its ``date`` field, else the date its file name starts
    with. Raises ValueError for an impossible date."""
    return _iso_date(rec.get("date")) or _iso_date(fname)


def worktree_roots(root) -> list[Path]:
    """``root`` first, then every other worktree of its repository (from
    ``git worktree list --porcelain``). Just ``root`` if git is unavailable or
    ``root`` is not in a repository."""
    root = Path(root)
    roots = [root]
    try:
        out = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return roots
    if out.returncode != 0:
        return roots
    seen = {os.path.realpath(root)}
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            wt = Path(line[len("worktree "):])
            real = os.path.realpath(wt)
            if real not in seen and wt.is_dir():
                seen.add(real)
                roots.append(wt)
    return roots


def load_run_records(root) -> tuple[list[dict], list[dict]]:
    """Every ``.claude/runs/*.yml`` in every worktree of the project. A file
    with the same name and content in several worktrees is read once."""
    records, errors = [], []
    seen: set[tuple[str, str]] = set()
    root = Path(root)
    for wt in worktree_roots(root):
        runs = wt / ".claude" / "runs"
        if not runs.is_dir():
            continue
        for p in sorted(list(runs.glob("*.yml")) + list(runs.glob("*.yaml"))):
            rel = str(p.relative_to(wt))
            where = {} if wt == root else {"_worktree": redact(str(wt))}
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                errors.append({"file": rel, **where, "error": redact(str(e)), "raw": ""})
                continue
            if (p.name, text) in seen:
                continue
            seen.add((p.name, text))
            try:
                rec = parse_yaml_lite(text)
                if not isinstance(rec, dict):
                    raise YamlLiteError("not a mapping")
                rec["date"] = _rec_date(rec, p.name)
                rec = _redact_tree(rec)
            except Exception as e:  # YamlLiteError, an impossible date, anything odd: never fatal
                errors.append({"file": rel, **where, "error": redact(str(e)), "raw": redact(text)[:4000]})
                continue
            rec["_file"] = rel
            rec.update(where)
            records.append(rec)
    return records, errors


def _findings(rec) -> list[dict]:
    f = rec.get("findings")
    return [x for x in f if isinstance(x, dict)] if isinstance(f, list) else []


def category_counts(records, since: datetime) -> dict:
    cutoff = since.date().isoformat()
    out: dict[str, dict] = {}
    for rec in records:
        d = rec.get("date")
        if not d or d < cutoff:
            continue
        for f in _findings(rec):
            cat = f.get("category")
            if not isinstance(cat, str) or not cat:
                continue
            c = out.setdefault(cat, {"count": 0, "by_severity": {}, "last_seen": None})
            c["count"] += 1
            sev = str(f.get("severity") or "unknown")
            c["by_severity"][sev] = c["by_severity"].get(sev, 0) + 1
            if c["last_seen"] is None or d > c["last_seen"]:
                c["last_seen"] = d
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))


def load_ledger(path, scope: str) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"path": str(path), "scope": scope, "rules": [], "error": str(e), "raw": ""}
    try:
        doc = parse_yaml_lite(text) or {}
        rules = doc.get("rules") if isinstance(doc, dict) else None
        rules = [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
        return {"path": str(path), "scope": scope, "rules": _redact_tree(rules)}
    except (YamlLiteError, RecursionError) as e:
        return {"path": str(path), "scope": scope, "rules": [], "error": redact(str(e)), "raw": redact(text)[:8000]}


def ledger_report(ledger: dict | None, records, now: datetime) -> dict | None:
    if ledger is None:
        return None
    rules = []
    for r in ledger["rules"]:
        try:
            added = _iso_date(r.get("added"))
        except ValueError as e:
            rules.append({**r, "error": str(e), "occurrences_since": None, "last_occurrence": None,
                          "records_since_added": None, "days_since_added": None, "last_verdict": None})
            continue
        occ, last, active = 0, None, 0
        if added:
            for rec in records:
                d = rec.get("date")
                if not d or d <= added:
                    continue
                active += 1
                for f in _findings(rec):
                    if f.get("category") == r.get("category"):
                        occ += 1
                        last = d if last is None or d > last else last
        history = r.get("history") if isinstance(r.get("history"), list) else []
        last_hist = history[-1] if history and isinstance(history[-1], dict) else {}
        rules.append({
            **r,
            "occurrences_since": occ,
            "last_occurrence": last,
            "records_since_added": active,
            "days_since_added": (now.date() - date.fromisoformat(added)).days if added else None,
            "last_verdict": last_hist.get("verdict"),
        })
    out = {k: v for k, v in ledger.items() if k != "rules"}
    out["path"] = redact(out.get("path", ""))
    out["rules"] = rules
    return out


TRANSCRIPT_LOOKBACK_MAX = timedelta(days=90)


def transcript_window(since: datetime, now: datetime, ledgers) -> tuple[datetime, str | None]:
    """The window for transcript signals: ``since``, extended back to the
    ``added`` date of the oldest rule in ``ledgers`` (so every rule can be
    verified against signals since it was added), but never further back than
    90 days before ``now``. Returns the start and, if extended, which rule."""
    oldest = None
    for ledger in ledgers:
        for r in (ledger or {}).get("rules", []):
            try:
                added = _iso_date(r.get("added"))
            except ValueError:
                continue
            if added and (oldest is None or added < oldest[0]):
                oldest = (added, r.get("id") or r.get("category") or "?")
    if oldest is None:
        return since, None
    start = max(datetime.fromisoformat(oldest[0]).replace(tzinfo=timezone.utc), now - TRANSCRIPT_LOOKBACK_MAX)
    if start >= since:
        return since, None
    capped = " (capped at 90 days)" if start == now - TRANSCRIPT_LOOKBACK_MAX else ""
    return start, f"ledger rule {oldest[1]} added {oldest[0]}{capped}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return Path(base) / "projects"


def _expand_transcripts(items) -> list[Path]:
    out = []
    for item in items:
        p = Path(item).expanduser()
        out.extend(sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="project root (git root); default: current directory")
    ap.add_argument("--since", default="30d", help="window: 30d, 12h, 2w or an ISO date (default 30d)")
    ap.add_argument("--transcripts", nargs="*", help="transcript files or directories (default: discover)")
    ap.add_argument("--projects-dir", help="Claude Code projects dir (default ~/.claude/projects)")
    ap.add_argument("--user-ledger", help="user-scope ledger (default ~/.claude/rules-ledger.yml)")
    ap.add_argument("--max-signals", type=int, default=500, help="cap on signals listed (counts stay exact)")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    started = time.monotonic()
    now = _parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    try:
        since = parse_since(args.since, now)
    except ValueError as e:
        ap.error(str(e))
    root = os.path.abspath(args.root)

    user_ledger = Path(args.user_ledger) if args.user_ledger else Path.home() / ".claude" / "rules-ledger.yml"
    project_ledger = load_ledger(Path(root) / ".claude" / "rules-ledger.yml", "project")
    user_ledger = load_ledger(user_ledger, "user")
    t_since, extended_for = transcript_window(since, now, [project_ledger, user_ledger])

    if args.transcripts is not None:
        paths = _expand_transcripts(args.transcripts)
    else:
        paths = discover_transcripts(root, Path(args.projects_dir) if args.projects_dir else _default_projects_dir())
    mined = mine_transcripts(paths, t_since, max_signals=args.max_signals)

    # Run records are small: all of them are read whatever the window, so the
    # ledger sees every record since each rule was added.
    records, record_errors = load_run_records(root)
    in_window = [r for r in records if r.get("date") and r["date"] >= since.date().isoformat()]

    mined["stats"]["runtime_seconds"] = round(time.monotonic() - started, 3)
    out = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "project_root": redact(root),
        "since": since.isoformat(timespec="seconds"),
        "window": {
            "since": since.isoformat(timespec="seconds"),
            "category_counts_since": since.isoformat(timespec="seconds"),
            "run_records_for_ledger": "all",
            "transcripts_since": t_since.isoformat(timespec="seconds"),
            "transcripts_extended_for": extended_for,
        },
        "transcripts": mined["stats"],
        "signal_counts": mined["signal_counts"],
        "signals": mined["signals"],
        "run_records": {
            "count_total": len(records),
            "count_in_window": len(in_window),
            "records": in_window,
            "parse_errors": record_errors,
        },
        "category_counts": category_counts(records, since),
        "ledgers": {
            "project": ledger_report(project_ledger, records, now),
            "user": ledger_report(user_ledger, records, now),
        },
    }
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
