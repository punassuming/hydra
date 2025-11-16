import platform
from worker.utils.os_exec import run_command, run_python
from worker.executor import execute_job
from worker.utils.completion import evaluate_completion


def test_os_exec_echo():
    system = platform.system().lower()
    if system.startswith("win"):
        rc, out, err = run_command("echo hello", shell="cmd")
    else:
        rc, out, err = run_command("echo hello", shell="bash")
    assert rc == 0
    assert "hello" in out.strip().lower()


def test_python_executor_runs_inline_code():
    rc, out, _ = run_python("print('hydra')", interpreter="python3")
    assert rc == 0
    assert "hydra" in out


def test_execute_job_shell_executor():
    job = {"executor": {"type": "shell", "script": "echo hydra-shell", "shell": "bash"}, "timeout": 5}
    rc, out, _ = execute_job(job)
    assert rc == 0
    assert "hydra-shell" in out


def test_execute_job_python_executor():
    job = {"executor": {"type": "python", "code": "print('from python')", "interpreter": "python3"}, "timeout": 5}
    rc, out, _ = execute_job(job)
    assert rc == 0
    assert "from python" in out


def test_execute_job_external_executor():
    binary = "cmd.exe" if platform.system().lower().startswith("win") else "/usr/bin/env"
    args = ["/c", "echo external"] if "cmd" in binary else ["echo", "external"]
    job = {"executor": {"type": "external", "command": binary, "args": args}}
    rc, out, _ = execute_job(job)
    assert rc == 0
    assert "external" in out.lower()


def test_completion_exit_code_evaluation():
    job = {"completion": {"exit_codes": [0]}}
    ok, reason = evaluate_completion(job, 0, "", "")
    assert ok
    assert "criteria" in reason.lower()


def test_completion_stdout_contains():
    job = {"completion": {"exit_codes": [0], "stdout_contains": ["ready"]}}
    ok, reason = evaluate_completion(job, 0, "system ready", "")
    assert ok
    ok, reason = evaluate_completion(job, 0, "no match", "")
    assert not ok
    assert "stdout" in reason.lower()
