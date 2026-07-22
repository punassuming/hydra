import os
import platform
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..runtime import _resolve_shell


def _merged_env(extra: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged = os.environ.copy()
    if extra:
        merged.update({k: str(v) for k, v in extra.items()})
    return merged


def _run(cmd: Sequence[str], timeout: Optional[int], env: Optional[Dict[str, str]], workdir: Optional[str]):
    proc = subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout if timeout and timeout > 0 else None,
        cwd=workdir,
        env=_merged_env(env),
    )
    return proc.returncode, proc.stdout, proc.stderr


def _run_with_callbacks(
    cmd: Sequence[str],
    timeout: Optional[int],
    env: Optional[Dict[str, str]],
    workdir: Optional[str],
    on_stdout: Optional[Callable[[str], None]] = None,
    on_stderr: Optional[Callable[[str], None]] = None,
    kill_event: Optional["threading.Event"] = None,
) -> Tuple[int, str, str]:
    """
    Run a command, streaming stdout/stderr via callbacks while still returning full buffers.
    """
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=workdir,
        env=_merged_env(env),
    )
    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def _drain(pipe, sink: List[str], cb: Optional[Callable[[str], None]]):
        for line in iter(pipe.readline, ""):
            sink.append(line)
            if cb:
                try:
                    cb(line)
                except Exception:
                    pass
        pipe.close()

    def _watch_kill():
        if kill_event is None:
            return
        kill_event.wait()
        try:
            proc.terminate()
            time.sleep(2)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    threads = []
    if proc.stdout:
        t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_lines, on_stdout), daemon=True)
        t_out.start()
        threads.append(t_out)
    if proc.stderr:
        t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_lines, on_stderr), daemon=True)
        t_err.start()
        threads.append(t_err)
    if kill_event is not None:
        t_kill = threading.Thread(target=_watch_kill, daemon=True)
        t_kill.start()

    try:
        proc.wait(timeout=timeout if timeout and timeout > 0 else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    for t in threads:
        t.join(timeout=1)

    return proc.returncode, "".join(stdout_lines), "".join(stderr_lines)


def run_command(
    command: str,
    shell: str = "bash",
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    workdir: Optional[str] = None,
) -> Tuple[int, str, str]:
    system = platform.system().lower()
    shell_lc = (shell or "bash").lower()
    shell_path = _resolve_shell(shell_lc)
    if system.startswith("linux") or system == "darwin":
        if shell_lc in ("bash", "cmd", "powershell"):
            cmd = [shell_path, "-lc", command]
        else:
            cmd = [shell_path, "-lc", command]
    elif system.startswith("win"):
        if shell_lc == "powershell":
            cmd = [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
        elif shell_lc == "cmd":
            cmd = [shell_path, "/c", command]
        elif shell_lc == "bash":
            cmd = [shell_path, "-lc", command]
        else:
            cmd = [_resolve_shell("powershell"), "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        cmd = [shell_path, "-lc", command]

    return _run(cmd, timeout, env, workdir)


def run_python(
    code: str,
    interpreter: str = "python3",
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    workdir: Optional[str] = None,
) -> Tuple[int, str, str]:
    cmd = [interpreter, "-c", code]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout, env, workdir)


def run_external(
    binary: str,
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    workdir: Optional[str] = None,
) -> Tuple[int, str, str]:
    cmd = [binary]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout, env, workdir)
