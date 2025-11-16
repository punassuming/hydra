import platform
import subprocess
from typing import Tuple, Optional


def run_command(command: str, shell: str = "bash", timeout: Optional[int] = None) -> Tuple[int, str, str]:
    system = platform.system().lower()
    if system.startswith("linux") or system == "darwin":
        if shell.lower() == "bash":
            cmd = ["/bin/bash", "-lc", command]
        elif shell.lower() == "cmd":
            # not typical on linux; emulate via bash
            cmd = ["/bin/bash", "-lc", command]
        elif shell.lower() == "powershell":
            # if pwsh installed; fallback to bash
            cmd = ["/bin/bash", "-lc", command]
        else:
            cmd = ["/bin/bash", "-lc", command]
    elif system.startswith("win"):
        if shell.lower() == "powershell":
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        elif shell.lower() == "cmd":
            cmd = ["cmd.exe", "/c", command]
        else:
            # default to powershell on windows
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        # default fallback
        cmd = ["/bin/bash", "-lc", command]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout if timeout and timeout > 0 else None,
    )
    return proc.returncode, proc.stdout, proc.stderr

