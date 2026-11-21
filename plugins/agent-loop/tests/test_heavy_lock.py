"""heavy_lock.py: heavy jobs run one at a time on the machine, across leads and repositories
(docs/DESIGN.md, "Delegated runs").

Exit codes: the command's own; 75 the lock is busy and nothing ran; 74 cannot lock and nothing ran;
2 usage; 127 the command was not found.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fcntl")

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "heavy_lock.py"
PY = sys.executable


def _lock(lock, *cmd, wait=None, label=None, **kw):
    args = [PY, str(SCRIPT), "--lock", str(lock)]
    if wait is not None:
        args += ["--wait", str(wait)]
    if label is not None:
        args += ["--label", label]
    return args + ["--", *cmd]


def _run(*args, **kw):
    return subprocess.run(args[0] if len(args) == 1 else args, capture_output=True, text=True, timeout=60, **kw)


def _py(code):
    return [PY, "-c", code]


def _wait_for(path, timeout=20):
    end = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < end, f"{path} never appeared"
        time.sleep(0.05)


def _holder(tmp_path, lock, seconds, label="lead-a"):
    """Start a run that holds the lock; returns once its command is running."""
    started = tmp_path / f"started-{label}"
    code = (f"import pathlib, time; p = pathlib.Path({str(started)!r}); p.write_text('start'); "
            f"time.sleep({seconds}); p.write_text('end')")
    proc = subprocess.Popen(_lock(lock, *_py(code), label=label), start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _wait_for(started)
    return proc, started


@pytest.mark.parametrize("status", [0, 3])
def test_runs_the_command_and_passes_its_exit_code_through(tmp_path, status):
    out = _run(_lock(tmp_path / "heavy.lock", *_py(f"print('ran'); raise SystemExit({status})")))
    assert out.returncode == status and "ran" in out.stdout


def test_a_busy_lock_runs_nothing_and_says_who_holds_it(tmp_path):
    lock = tmp_path / "heavy.lock"
    proc, _ = _holder(tmp_path, lock, 3)
    try:
        marker = tmp_path / "ran"
        out = _run(_lock(lock, *_py(f"open({str(marker)!r}, 'w').close()"), wait=0))
        assert out.returncode == 75
        assert "busy" in out.stderr and "lead-a" in out.stderr and "nothing was run" in out.stderr
        assert not marker.exists()
    finally:
        proc.wait(timeout=30)


def test_a_waiting_run_starts_only_after_the_holder_finishes(tmp_path):
    lock = tmp_path / "heavy.lock"
    proc, started = _holder(tmp_path, lock, 1)
    seen = tmp_path / "seen"
    code = f"import pathlib; pathlib.Path({str(seen)!r}).write_text(pathlib.Path({str(started)!r}).read_text())"
    out = _run(_lock(lock, *_py(code), wait=30, label="lead-b"))
    proc.wait(timeout=30)
    assert out.returncode == 0, out.stderr
    assert seen.read_text() == "end"


def test_the_lock_is_released_when_the_holder_dies(tmp_path):
    lock = tmp_path / "heavy.lock"
    proc, _ = _holder(tmp_path, lock, 60)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)
    out = _run(_lock(lock, *_py("print('ran')"), wait=10))
    assert out.returncode == 0 and "ran" in out.stdout


def test_the_command_keeps_the_lock_if_the_wrapper_dies(tmp_path):
    # The heavy job itself holds the lock: killing only the wrapper must not let a second job start.
    lock = tmp_path / "heavy.lock"
    proc, started = _holder(tmp_path, lock, 3)
    try:
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        out = _run(_lock(lock, *_py("print('ran')"), wait=0))
        assert out.returncode == 75 and "ran" not in out.stdout
    finally:
        if _alive_group(proc.pid):
            os.killpg(proc.pid, signal.SIGKILL)


def _alive_group(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def test_a_symlinked_lock_is_refused(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("keep\n")
    lock = tmp_path / "heavy.lock"
    lock.symlink_to(target)
    marker = tmp_path / "ran"
    out = _run(_lock(lock, *_py(f"open({str(marker)!r}, 'w').close()")))
    assert out.returncode == 74 and "cannot lock" in out.stderr
    assert not marker.exists() and target.read_text() == "keep\n"


def test_a_lock_in_a_missing_directory_cannot_lock(tmp_path):
    out = _run(_lock(tmp_path / "missing" / "heavy.lock", *_py("print('ran')")))
    assert out.returncode == 74 and "cannot lock" in out.stderr and "ran" not in out.stdout


def test_a_missing_command_is_127_and_the_lock_is_freed(tmp_path):
    lock = tmp_path / "heavy.lock"
    out = _run(_lock(lock, str(tmp_path / "no-such-command")))
    assert out.returncode == 127 and "not found" in out.stderr
    assert _run(_lock(lock, *_py("print('ran')"), wait=0)).returncode == 0


@pytest.mark.parametrize("args", [[], ["--lock", "x"], ["--lock", "x", "--"]]
                         + [["--lock", "x", "--wait", w, "--", "true"] for w in ("-1", "nan", "inf", "-inf", "3601", "1e9")])
def test_usage_errors_run_nothing(tmp_path, args):
    out = _run([PY, str(SCRIPT), *args], cwd=tmp_path)
    assert out.returncode == 2 and "usage:" in out.stderr


def test_the_default_wait_returns_well_within_a_foreground_tool_call():
    import heavy_lock
    assert heavy_lock.DEFAULT_WAIT == 90 and heavy_lock.MAX_WAIT == 3600


def _env(**kw):
    env = {k: v for k, v in os.environ.items() if k != "XDG_CACHE_HOME"}
    env.update(kw)
    return env


@pytest.mark.parametrize("xdg", [True, False])
def test_the_default_lock_is_one_per_user_in_the_cache_directory(tmp_path, xdg):
    env = _env(XDG_CACHE_HOME=str(tmp_path / "cache")) if xdg else _env(HOME=str(tmp_path))
    base = tmp_path / "cache" if xdg else tmp_path / ".cache"
    out = _run([PY, str(SCRIPT), "--", *_py("print('ran')")], env=env)
    assert out.returncode == 0 and "ran" in out.stdout, out.stderr
    lock = base / "agent-loop" / "heavy.lock"
    assert lock.is_file()
    assert (lock.parent.stat().st_mode & 0o777) == 0o700 and (lock.stat().st_mode & 0o777) == 0o600


def test_the_default_lock_serialises_jobs_from_any_repository(tmp_path):
    env = _env(XDG_CACHE_HOME=str(tmp_path / "cache"))
    started = tmp_path / "started"
    holder = subprocess.Popen([PY, str(SCRIPT), "--label", "repo-a", "--", *_py(
        f"import pathlib, time; pathlib.Path({str(started)!r}).write_text('x'); time.sleep(3)")],
        env=env, cwd=tmp_path, start_new_session=True)
    try:
        _wait_for(started)
        other = tmp_path / "other-repo"
        other.mkdir()
        out = _run([PY, str(SCRIPT), "--wait", "0", "--", *_py("print('ran')")], env=env, cwd=other)
        assert out.returncode == 75 and "repo-a" in out.stderr
    finally:
        holder.wait(timeout=30)


def test_a_symlinked_lock_directory_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "agent-loop").symlink_to(real)
    out = _run([PY, str(SCRIPT), "--", *_py("print('ran')")], env=_env(XDG_CACHE_HOME=str(tmp_path / "cache")))
    assert out.returncode == 74 and "cannot lock" in out.stderr and "ran" not in out.stdout
    assert not (real / "heavy.lock").exists()


def test_a_lock_directory_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    import heavy_lock
    d = tmp_path / "agent-loop"
    d.mkdir(mode=0o700)
    monkeypatch.setattr(heavy_lock.os, "getuid", lambda: os.stat(d).st_uid + 1)
    with pytest.raises(OSError, match="not owned"):
        heavy_lock.lock_dir(d)
