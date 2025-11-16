import os
import platform
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple


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


def run_command(command: str, shell: str = "bash", timeout: Optional[int] = None,
                env: Optional[Dict[str, str]] = None, workdir: Optional[str] = None) -> Tuple[int, str, str]:
    system = platform.system().lower()
    shell_lc = (shell or "bash").lower()
    if system.startswith("linux") or system == "darwin":
        if shell_lc == "bash":
            cmd = ["/bin/bash", "-lc", command]
        elif shell_lc == "cmd":
            cmd = ["/bin/bash", "-lc", command]
        elif shell_lc == "powershell":
            cmd = ["/bin/bash", "-lc", command]
        else:
            cmd = ["/bin/bash", "-lc", command]
    elif system.startswith("win"):
        if shell_lc == "powershell":
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        elif shell_lc == "cmd":
            cmd = ["cmd.exe", "/c", command]
        else:
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        cmd = ["/bin/bash", "-lc", command]

    return _run(cmd, timeout, env, workdir)


def run_python(code: str, interpreter: str = "python3", args: Optional[List[str]] = None,
               timeout: Optional[int] = None, env: Optional[Dict[str, str]] = None,
               workdir: Optional[str] = None) -> Tuple[int, str, str]:
    cmd = [interpreter, "-c", code]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout, env, workdir)


def run_external(binary: str, args: Optional[List[str]] = None, timeout: Optional[int] = None,
                 env: Optional[Dict[str, str]] = None, workdir: Optional[str] = None) -> Tuple[int, str, str]:
    cmd = [binary]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout, env, workdir)
