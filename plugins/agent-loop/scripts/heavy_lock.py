#!/usr/bin/env python3
"""Run a heavy job only while holding a lock shared by every lead (docs/DESIGN.md, "Delegated runs").

``heavy_lock.py --lock <path> [--wait SECONDS] [--label TEXT] -- <command> [args...]``

Several leads started by ``/agent-loop:dispatch`` work in separate worktrees of one repository. Their
heavy jobs (full test suites, builds, mutation testing, fuzzing) must never run at the same time, so
each goes through this wrapper with the same lock file (the dispatcher passes its path). The wrapper
takes an exclusive ``flock`` on the file, writes who holds it into it, runs the command and exits with
the command's exit code. The command inherits the lock, so it stays held until the command and
anything it started that kept the descriptor have exited, even if the wrapper itself is killed; the
kernel releases it when they die, so a crashed run never leaves a stale lock.

Exit codes: the command's own; 75 the lock stayed busy for ``--wait`` seconds (default 540, under a
ten-minute tool timeout) and nothing was run; 74 the lock could not be taken (no ``fcntl``, a missing
directory, a symlink) and nothing was run; 127 the command was not found; 2 usage. A message starting
``heavy_lock:`` on stderr is the wrapper's own. Standard library only; POSIX only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BUSY, CANNOT, NOT_FOUND = 75, 74, 127
POLL = 0.5


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
    ap.add_argument("--lock", required=True, help="the lock file every lead of the dispatch shares")
    ap.add_argument("--wait", type=float, default=540.0,
                    help="seconds to wait for a busy lock before giving up with exit 75 (default 540)")
    ap.add_argument("--label", default="", help="who is running, shown to anyone who finds the lock busy")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command and its arguments")
    args = ap.parse_args(argv)
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        ap.error("give the command after --")
    if args.wait < 0:
        ap.error("--wait must be 0 or more")

    try:
        import fcntl
    except ImportError:
        _say("cannot lock: fcntl is not available on this platform; nothing was run.")
        return CANNOT
    try:
        fd = _open(args.lock)
    except OSError as e:
        _say(f"cannot lock {args.lock}: {e.strerror or e}; nothing was run.")
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
            _say(f"cannot lock {args.lock}: {e.strerror or e}; nothing was run.")
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
