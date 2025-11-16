import platform
from worker.utils.os_exec import run_command


def test_os_exec_echo():
    system = platform.system().lower()
    if system.startswith("win"):
        rc, out, err = run_command("echo hello", shell="cmd")
    else:
        rc, out, err = run_command("echo hello", shell="bash")
    assert rc == 0
    assert "hello" in out.strip().lower()

