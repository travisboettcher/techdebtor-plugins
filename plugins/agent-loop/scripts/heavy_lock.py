#!/usr/bin/env python3
"""Run a heavy job only while holding the user's one heavy-job lock (docs/DESIGN.md, "Delegated runs").

``heavy_lock.py [--lock <path>] [--wait SECONDS] [--label TEXT] -- <command> [args...]``

Leads started by ``/agent-loop:dispatch`` work in separate worktrees, possibly of several repositories.
Their heavy jobs (full test suites, builds, mutation testing, fuzzing) must never run at the same
time anywhere on the machine, so each goes through this wrapper, which by default uses one lock per
user: ``${XDG_CACHE_HOME:-~/.cache}/agent-loop/heavy.lock``. The directory is created 0700 and the
file 0600; a directory that is a symlink or not owned by the user, or a lock file that is a symlink,
is refused. ``--lock`` names another file (tests). The wrapper takes an exclusive ``flock`` on the file, writes who holds it into it, runs the command and exits with
the command's exit code. The command inherits the lock, so it stays held until the command and
anything it started that kept the descriptor have exited, even if the wrapper itself is killed; the
kernel releases it when they die, so a crashed run never leaves a stale lock.

The time a tool call takes is the wait plus the job. ``--wait`` defaults to 90 seconds (at most 3600),
so a busy lock returns well inside a foreground tool call; run a job that may take minutes in the
background (the shell tool's ``run_in_background``) or with an explicit long tool timeout.

Exit codes: the command's own; 75 the lock stayed busy for ``--wait`` seconds and nothing was run;
74 the lock could not be taken (no ``fcntl``, a missing or unsafe directory, a symlink) and nothing
was run; 127 the command was not found; 2 usage. A message starting
``heavy_lock:`` on stderr is the wrapper's own. Standard library only; POSIX only.
"""

from __future__ import annotations

import argparse
import math
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

BUSY, CANNOT, NOT_FOUND = 75, 74, 127
POLL = 0.5
DEFAULT_WAIT, MAX_WAIT = 90, 3600


def default_lock() -> str:
    """``${XDG_CACHE_HOME:-~/.cache}/agent-loop/heavy.lock``: one lock per user, across repositories."""
    cache = os.environ.get("XDG_CACHE_HOME", "")
    if not os.path.isabs(cache):
        cache = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(cache, "agent-loop", "heavy.lock")


def lock_dir(path) -> None:
    """Create the lock's directory 0700 if missing; refuse one that is a symlink or not the user's."""
    path = os.fspath(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise OSError(f"{path} is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise OSError(f"{path} is not a directory")
    if st.st_uid != os.getuid():
        raise OSError(f"{path} is not owned by this user")


def _wait(value: str) -> float:
    try:
        w = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if not math.isfinite(w) or not 0 <= w <= MAX_WAIT:
        raise argparse.ArgumentTypeError(f"--wait must be from 0 to {MAX_WAIT} seconds")
    return w


def _say(msg: str) -> None:
    print(f"heavy_lock: {msg}", file=sys.stderr, flush=True)


def _open(path: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


def _holder(fd: int) -> str:
    try:
        return os.pread(fd, 300, 0).decode("utf-8", "replace").strip() or "unknown"
    except OSError:
        return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a heavy job while holding a shared lock.")
    ap.add_argument("--lock", help="the lock file (default: ${XDG_CACHE_HOME:-~/.cache}/agent-loop/heavy.lock)")
    ap.add_argument("--wait", type=_wait, default=float(DEFAULT_WAIT),
                    help=f"seconds to wait for a busy lock before giving up with exit 75 (default {DEFAULT_WAIT})")
    ap.add_argument("--label", default="", help="who is running, shown to anyone who finds the lock busy")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command and its arguments")
    args = ap.parse_args(argv)
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        ap.error("give the command after --")

    try:
        import fcntl
    except ImportError:
        _say("cannot lock: fcntl is not available on this platform; nothing was run.")
        return CANNOT
    lock = args.lock
    try:
        if lock is None:
            lock = default_lock()
            lock_dir(os.path.dirname(lock))
        fd = _open(lock)
        os.fchmod(fd, 0o600)
    except OSError as e:
        _say(f"cannot lock {lock}: {e.strerror or e}; nothing was run.")
        return CANNOT

    deadline = time.monotonic() + args.wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                _say(f"busy: held by {_holder(fd)}; nothing was run. Try again later; never run it without the lock.")
                return BUSY
            time.sleep(POLL)
        except OSError as e:
            _say(f"cannot lock {lock}: {e.strerror or e}; nothing was run.")
            return CANNOT

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    who = " ".join(x for x in (f"pid {os.getpid()}", args.label.replace("\n", " ")[:120], f"since {stamp}") if x)
    os.ftruncate(fd, 0)
    os.pwrite(fd, (who + "\n").encode("utf-8"), 0)
    try:
        proc = subprocess.Popen(cmd, pass_fds=(fd,))
    except (FileNotFoundError, PermissionError) as e:
        _say(f"command not found or not executable: {cmd[0]} ({e.strerror or e}).")
        return NOT_FOUND
    try:
        status = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        status = proc.wait()
    return 128 - status if status < 0 else status


if __name__ == "__main__":
    sys.exit(main())
