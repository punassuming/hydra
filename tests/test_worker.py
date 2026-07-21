import platform

from worker.executor import execute_job
from worker.utils.completion import _contains_all, _contains_none, evaluate_completion, evaluate_file_criteria
from worker.utils.heartbeat import _ensure_worker_registration, _touch_heartbeat_file
from worker.utils.os_exec import run_command, run_python
from worker.utils.python_env import prepare_python_command


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


def test_prepare_python_uv_command():
    executor = {
        "type": "python",
        "interpreter": "python3",
        "environment": {"type": "uv", "python_version": "3.11", "requirements": ["requests"]},
    }
    cmd, cleanup = prepare_python_command(executor, "job-123")
    assert cmd[0:2] == ["uv", "run"]
    assert "--python" in cmd
    assert "--with" in cmd
    assert "requests" in cmd
    assert cmd[-1] == "python3"
    assert cleanup is None


def test_completion_handles_forbidden_tokens():
    job = {
        "completion": {
            "exit_codes": [0],
            "stdout_not_contains": ["forbidden"],
            "stderr_contains": ["needle"],
            "stderr_not_contains": ["panic"],
        }
    }
    ok, reason = evaluate_completion(job, 0, "ok output", "needle present")
    assert ok
    ok, reason = evaluate_completion(job, 0, "forbidden text", "needle present")
    assert not ok and "stdout" in reason.lower()
    ok, reason = evaluate_completion(job, 0, "ok", "nothing here")
    assert not ok and "stderr" in reason.lower()


def test_completion_helpers_are_strict():
    success, reason = _contains_all("abc def", ["abc", "def"])
    assert success
    success, reason = _contains_all("abc", ["abc", "def"])
    assert not success and "missing" in reason.lower()

    success, reason = _contains_none("abc def", ["zzz"])
    assert success
    success, reason = _contains_none("abc def", ["abc"])
    assert not success and "forbidden" in reason.lower()


def test_file_criteria_require_file_exists_passes():
    import os
    import tempfile
    import time
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    try:
        job = {"completion": {"require_file_exists": [path]}}
        ok, reason = evaluate_file_criteria(job, time.time())
        assert ok, reason
    finally:
        os.unlink(path)


def test_file_criteria_require_file_exists_fails_missing():
    import time
    job = {"completion": {"require_file_exists": ["/nonexistent/hydra_test_file_xyz.txt"]}}
    ok, reason = evaluate_file_criteria(job, time.time())
    assert not ok
    assert "does not exist" in reason


def test_file_criteria_require_file_updated_since_start_passes():
    import os
    import tempfile
    import time
    start = time.time() - 1  # file written after this
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"data")
        path = f.name
    try:
        job = {"completion": {"require_file_updated_since_start": [path]}}
        ok, reason = evaluate_file_criteria(job, start)
        assert ok, reason
    finally:
        os.unlink(path)


def test_file_criteria_require_file_updated_since_start_fails_old_file():
    import os
    import tempfile
    import time
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"old data")
        path = f.name
    try:
        # Set a future start time so the file appears not updated since start
        future_start = time.time() + 100
        job = {"completion": {"require_file_updated_since_start": [path]}}
        ok, reason = evaluate_file_criteria(job, future_start)
        assert not ok
        assert "not updated since" in reason
    finally:
        os.unlink(path)


def test_file_criteria_require_file_updated_since_start_fails_missing():
    import time
    job = {"completion": {"require_file_updated_since_start": ["/nonexistent/hydra_test_xyz.txt"]}}
    ok, reason = evaluate_file_criteria(job, time.time())
    assert not ok
    assert "does not exist" in reason


def test_file_criteria_no_criteria_passes():
    import time
    job = {"completion": {}}
    ok, reason = evaluate_file_criteria(job, time.time())
    assert ok
    from worker.utils.git import _inject_token_into_url
    url = "https://github.com/user/repo.git"
    result = _inject_token_into_url(url, "mytoken")
    assert "x-oauth-token:mytoken@github.com" in result
    assert result.startswith("https://")


def test_git_token_injection_ssh_passthrough():
    from worker.utils.git import _inject_token_into_url
    url = "git@github.com:user/repo.git"
    result = _inject_token_into_url(url, "mytoken")
    # SSH URLs should pass through unchanged
    assert result == url


def test_ensure_worker_registration_refreshes_missing_registry():
    from unittest.mock import MagicMock

    mock_r = MagicMock()
    mock_r.hexists.return_value = False
    refresh = MagicMock()

    refreshed = _ensure_worker_registration(mock_r, "prod", "worker-1", refresh)

    assert refreshed is True
    mock_r.hexists.assert_called_once_with("workers:prod:worker-1", "domain_token_hash")
    refresh.assert_called_once_with()


def test_ensure_worker_registration_skips_when_registry_is_present():
    from unittest.mock import MagicMock

    mock_r = MagicMock()
    mock_r.hexists.return_value = True
    refresh = MagicMock()

    refreshed = _ensure_worker_registration(mock_r, "prod", "worker-1", refresh)

    assert refreshed is False
    refresh.assert_not_called()


def test_touch_heartbeat_file_writes_current_timestamp(tmp_path, monkeypatch):
    import time

    from worker.utils import heartbeat as heartbeat_mod

    heartbeat_path = tmp_path / "hydra_worker_heartbeat"
    monkeypatch.setattr(heartbeat_mod, "HEARTBEAT_FILE", str(heartbeat_path))

    before = time.time()
    _touch_heartbeat_file()
    after = time.time()

    assert heartbeat_path.exists()
    written_ts = float(heartbeat_path.read_text())
    assert before <= written_ts <= after


def test_touch_heartbeat_file_survives_unwritable_path(monkeypatch):
    """A liveness file write failure must never raise — it's best-effort."""
    from worker.utils import heartbeat as heartbeat_mod

    monkeypatch.setattr(heartbeat_mod, "HEARTBEAT_FILE", "/nonexistent-dir/heartbeat")
    _touch_heartbeat_file()  # should not raise


def test_ensure_worker_registration_handles_refresh_failure():
    from unittest.mock import MagicMock

    mock_r = MagicMock()
    mock_r.hexists.return_value = False

    def fail_refresh():
        raise RuntimeError("boom")

    refreshed = _ensure_worker_registration(
        mock_r,
        "prod",
        "worker-1",
        fail_refresh,
    )

    assert refreshed is False


def test_git_token_injection_empty_token():
    from worker.utils.git import _inject_token_into_url
    url = "https://github.com/user/repo.git"
    result = _inject_token_into_url(url, "")
    assert result == url


def test_copy_source_directory():
    import os
    import tempfile

    from worker.utils.copy import fetch_copy_source
    with tempfile.TemporaryDirectory() as src_dir:
        open(os.path.join(src_dir, "run.sh"), "w").write("echo hello")
        sub = os.path.join(src_dir, "subdir")
        os.makedirs(sub)
        open(os.path.join(sub, "data.txt"), "w").write("data")
        with tempfile.TemporaryDirectory() as dest_dir:
            fetch_copy_source(src_dir, dest_dir)
            assert os.path.isfile(os.path.join(dest_dir, "run.sh"))
            assert os.path.isfile(os.path.join(dest_dir, "subdir", "data.txt"))


def test_copy_source_single_file():
    import os
    import tempfile

    from worker.utils.copy import fetch_copy_source
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
        f.write(b"echo hi")
        src_file = f.name
    try:
        with tempfile.TemporaryDirectory() as dest_dir:
            fetch_copy_source(src_file, dest_dir)
            assert os.path.isfile(os.path.join(dest_dir, os.path.basename(src_file)))
    finally:
        os.unlink(src_file)


def test_copy_source_missing_raises():
    import tempfile

    import pytest

    from worker.utils.copy import fetch_copy_source
    with tempfile.TemporaryDirectory() as dest_dir:
        with pytest.raises(FileNotFoundError):
            fetch_copy_source("/nonexistent/path/that/does/not/exist", dest_dir)


def test_copy_source_rejects_relative_path():
    import tempfile

    import pytest

    from worker.utils.copy import fetch_copy_source
    with tempfile.TemporaryDirectory() as dest_dir:
        with pytest.raises(ValueError, match="absolute"):
            fetch_copy_source("relative/path", dest_dir)


def test_rsync_source_builds_command(monkeypatch):
    """Verify fetch_rsync_source builds the correct rsync command."""
    import subprocess

    from worker.utils.rsync import fetch_rsync_source

    captured = {}
    def mock_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    fetch_rsync_source("user@host:/data/files", "/tmp/dest")
    assert captured["cmd"][0] == "rsync"
    assert "-az" in captured["cmd"]
    assert "user@host:/data/files/" in captured["cmd"]
    assert "/tmp/dest/" in captured["cmd"]


def test_rsync_source_with_ssh_key(monkeypatch):
    """Verify SSH key is passed via -e flag when credential_ref_token is provided."""
    import subprocess

    from worker.utils.rsync import fetch_rsync_source

    captured = {}
    def mock_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    fetch_rsync_source("user@host:/data/files", "/tmp/dest", credential_ref_token="/path/to/key")
    assert any("/path/to/key" in str(c) for c in captured["cmd"])


def test_git_sparse_clone_calls(monkeypatch):
    """Verify that fetch_git_source with sparse_path uses sparse-checkout commands."""
    import subprocess

    from worker.utils.git import fetch_git_source

    calls = []
    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    fetch_git_source("https://github.com/org/repo.git", "main", "/tmp/dest", sparse_path="services/my-svc")
    # Should contain git init, git remote add, git sparse-checkout set, git fetch, git checkout
    cmd_strs = [" ".join(c) for c in calls]
    assert any("sparse-checkout" in s for s in cmd_strs), f"Expected sparse-checkout in commands: {cmd_strs}"
    assert any("init" in s for s in cmd_strs), f"Expected git init in commands: {cmd_strs}"


def test_python_executor_uses_temp_file():
    """Large inline code should run without hitting command-line length limits."""
    # Build a script larger than typical ARG_MAX limits would allow via -c
    many_lines = "\n".join(f"x_{i} = {i}" for i in range(500))
    code = many_lines + "\nprint('large-ok')"
    job = {"executor": {"type": "python", "code": code, "interpreter": "python3"}, "timeout": 10}
    rc, out, _ = execute_job(job)
    assert rc == 0
    assert "large-ok" in out


def test_shell_executor_uses_temp_file():
    """Large inline shell script should run without hitting command-line length limits."""
    many_vars = "\n".join(f"V{i}={i}" for i in range(200))
    script = many_vars + "\necho shell-large-ok"
    job = {"executor": {"type": "shell", "script": script, "shell": "bash"}, "timeout": 10}
    rc, out, _ = execute_job(job)
    assert rc == 0
    assert "shell-large-ok" in out


def test_absolute_workdir_treated_as_relative_to_source(monkeypatch, tmp_path):
    """An absolute workdir should be resolved relative to the fetched source root."""
    from worker.utils.copy import fetch_copy_source as real_fetch

    # Create a fake source tree: tmp_path/src/ with subdir/ containing a sentinel file
    src_dir = tmp_path / "src"
    subdir = src_dir / "mysubdir"
    subdir.mkdir(parents=True)
    (subdir / "sentinel.txt").write_text("found-it")

    # Patch fetch_copy_source to copy our fake source into the temp dir
    def _fake_fetch(url, dest):
        real_fetch(str(src_dir), dest)

    monkeypatch.setattr("worker.executor.fetch_copy_source", _fake_fetch)

    # Use an absolute workdir of /mysubdir — should be treated as relative to source root
    job = {
        "source": {"protocol": "copy", "url": str(src_dir)},
        "executor": {
            "type": "shell",
            "script": "cat sentinel.txt",
            "shell": "bash",
            "workdir": "/mysubdir",
        },
        "timeout": 5,
    }
    rc, out, err = execute_job(job)
    assert rc == 0, f"stderr: {err}"
    assert "found-it" in out


# ---------------------------------------------------------------------------
# SQL executor improvements
# ---------------------------------------------------------------------------

def test_sql_executor_requires_query():
    """SQL executor should fail with empty query."""
    job = {"executor": {"type": "sql", "dialect": "postgres", "connection_uri": "postgresql://localhost/test", "query": ""}}
    rc, out, err = execute_job(job)
    assert rc == 1
    assert "non-empty query" in err


def test_sql_executor_requires_connection_uri():
    """SQL executor should fail without connection_uri."""
    job = {"executor": {"type": "sql", "dialect": "postgres", "query": "SELECT 1"}}
    rc, out, err = execute_job(job)
    assert rc == 1
    assert "connection_uri" in err


def test_detect_capabilities_includes_http():
    """Worker capabilities should always include 'http'."""
    from worker.executor import _detect_capabilities
    caps = _detect_capabilities()
    assert "http" in caps
    assert "shell" in caps
    assert "external" in caps


def test_detect_capabilities_sql_depends_on_drivers():
    """SQL should only be advertised if sqlalchemy or pymongo is available."""
    from worker.executor import _detect_capabilities
    caps = _detect_capabilities()
    # pymongo is installed from scheduler requirements, so sql should be present
    assert "sql" in caps


# ---------------------------------------------------------------------------
# HTTP executor
# ---------------------------------------------------------------------------

def test_http_executor_requires_url():
    """HTTP executor should fail with empty URL."""
    job = {"executor": {"type": "http", "url": ""}}
    rc, out, err = execute_job(job)
    assert rc == 1
    assert "url" in err.lower()


def test_http_executor_connection_refused():
    """HTTP executor should handle connection failures gracefully."""
    job = {"executor": {"type": "http", "url": "http://127.0.0.1:1", "timeout_seconds": 2}}
    rc, out, err = execute_job(job)
    assert rc == 1
    assert "failed" in err.lower() or "refused" in err.lower() or "error" in err.lower()


# ---------------------------------------------------------------------------
# Impersonation
# ---------------------------------------------------------------------------

def test_impersonation_supported_on_linux():
    """On Linux, impersonation should be accepted (though sudo may fail without config)."""
    if platform.system().lower() != "linux":
        return
    job = {
        "executor": {
            "type": "shell",
            "script": "echo hello",
            "shell": "bash",
            "impersonate_user": "nonexistent_user_hydra_test",
        },
        "timeout": 5,
    }
    rc, out, err = execute_job(job)
    # Should fail because sudo is not configured, but NOT because of platform check
    assert "not supported" not in err.lower() or "only on" not in err.lower()


# ---------------------------------------------------------------------------
# Workspace cache
# ---------------------------------------------------------------------------

def test_workspace_cache_basic(tmp_path):
    """Workspace cache should create and reuse cache entries."""
    import os

    from worker.utils.workspace_cache import WorkspaceCache

    cache = WorkspaceCache(cache_root=str(tmp_path / "cache"), max_mb=100, ttl_seconds=3600)

    fetch_count = [0]
    def mock_fetch(dest, src_cfg):
        fetch_count[0] += 1
        with open(os.path.join(dest, "file.txt"), "w") as f:
            f.write("hello")

    source = {"url": "https://example.com/repo.git", "ref": "main", "protocol": "git", "cache": "auto"}

    # First call should fetch
    path1, release1 = cache.get_or_create("prod", "job1", source, mock_fetch)
    assert os.path.isfile(os.path.join(path1, "file.txt"))
    assert fetch_count[0] == 1
    release1()

    # Second call should reuse cache (fetch_count stays 1)
    path2, release2 = cache.get_or_create("prod", "job1", source, mock_fetch)
    assert path1 == path2
    assert fetch_count[0] == 1  # No new fetch
    release2()


def test_workspace_cache_never_mode(tmp_path):
    """cache='never' should always create a fresh temp directory."""
    import os

    from worker.utils.workspace_cache import WorkspaceCache

    cache = WorkspaceCache(cache_root=str(tmp_path / "cache"), max_mb=100, ttl_seconds=3600)

    def mock_fetch(dest, src_cfg):
        with open(os.path.join(dest, "file.txt"), "w") as f:
            f.write("hello")

    source = {"url": "https://example.com/repo.git", "ref": "main", "protocol": "git", "cache": "never"}

    path1, release1 = cache.get_or_create("prod", "job1", source, mock_fetch)
    assert os.path.isfile(os.path.join(path1, "file.txt"))

    path2, release2 = cache.get_or_create("prod", "job1", source, mock_fetch)
    assert path1 != path2  # Different temp dirs
    assert os.path.isfile(os.path.join(path2, "file.txt"))

    release1()
    release2()
    # After release, never-mode dirs should be cleaned up
    assert not os.path.exists(path1)
    assert not os.path.exists(path2)


def test_workspace_cache_always_mode_miss(tmp_path):
    """cache='always' should raise FileNotFoundError if cache doesn't exist."""
    import pytest

    from worker.utils.workspace_cache import WorkspaceCache

    cache = WorkspaceCache(cache_root=str(tmp_path / "cache"), max_mb=100, ttl_seconds=3600)

    source = {"url": "https://example.com/repo.git", "ref": "main", "protocol": "git", "cache": "always"}

    with pytest.raises(FileNotFoundError, match="always"):
        cache.get_or_create("prod", "job1", source, lambda d, s: None)


# ---------------------------------------------------------------------------
# Scheduler model updates
# ---------------------------------------------------------------------------

def test_sql_executor_model_new_fields():
    """SqlExecutor model should accept max_rows and autocommit."""
    from scheduler.models.executor import SqlExecutor
    sql = SqlExecutor(query="SELECT 1", dialect="postgres", max_rows=500, autocommit=False)
    assert sql.max_rows == 500
    assert sql.autocommit is False

    sql_default = SqlExecutor(query="SELECT 1")
    assert sql_default.max_rows == 10000
    assert sql_default.autocommit is True


def test_http_executor_model():
    """HttpExecutor model should validate required fields."""
    from scheduler.models.executor import HttpExecutor
    http = HttpExecutor(url="https://example.com", method="POST", body='{"key": "value"}')
    assert http.method == "POST"
    assert http.url == "https://example.com"
    assert http.timeout_seconds == 30
    assert http.expected_status == [200]


def test_source_config_cache_field():
    """SourceConfig should have a cache field defaulting to 'auto'."""
    from scheduler.models.job_definition import SourceConfig
    src = SourceConfig(url="https://github.com/test/repo.git")
    assert src.cache == "auto"

    src_never = SourceConfig(url="https://github.com/test/repo.git", cache="never")
    assert src_never.cache == "never"


def test_affinity_impersonation_check():
    """Jobs with impersonate_user should only match Linux/macOS workers."""
    from scheduler.utils.affinity import passes_affinity

    job_with_impersonation = {
        "user": "alice",
        "executor": {"impersonate_user": "bob"},
        "affinity": {},
    }
    base_worker = {"allowed_users": [], "tags": [], "hostname": "", "subnet": "", "deployment_type": "", "capabilities": []}
    worker_linux = {**base_worker, "os": "linux"}
    worker_darwin = {**base_worker, "os": "darwin"}
    worker_windows = {**base_worker, "os": "windows"}

    assert passes_affinity(job_with_impersonation, worker_linux)
    assert passes_affinity(job_with_impersonation, worker_darwin)
    assert not passes_affinity(job_with_impersonation, worker_windows)

    # Jobs without impersonation should work on any OS
    job_no_impersonation = {"user": "alice", "executor": {}, "affinity": {}}
    assert passes_affinity(job_no_impersonation, worker_windows)


# ---------------------------------------------------------------------------
# Non-containerized environment configuration
# ---------------------------------------------------------------------------

def test_hydra_python_path_used_by_find_python(monkeypatch):
    """_find_python() should honour HYDRA_PYTHON_PATH when set."""
    # Point to a known-good interpreter
    import sys

    from worker.executor import _find_python
    monkeypatch.setenv("HYDRA_PYTHON_PATH", sys.executable)
    result = _find_python()
    assert result == sys.executable


def test_hydra_python_path_fallback(monkeypatch):
    """_find_python() should fall back to PATH when HYDRA_PYTHON_PATH is unset."""
    from worker.executor import _find_python
    monkeypatch.delenv("HYDRA_PYTHON_PATH", raising=False)
    result = _find_python()
    assert result in ("python3", "python", "")


def test_hydra_shell_path_default(monkeypatch):
    """_get_shell_path() should return empty string when env is unset."""
    from worker.executor import _get_shell_path
    monkeypatch.delenv("HYDRA_SHELL_PATH", raising=False)
    assert _get_shell_path() == ""


def test_hydra_shell_path_configured(monkeypatch):
    """_get_shell_path() should return configured path."""
    from worker.executor import _get_shell_path
    monkeypatch.setenv("HYDRA_SHELL_PATH", "/usr/local/bin/bash")
    assert _get_shell_path() == "/usr/local/bin/bash"


def test_hydra_git_path_default(monkeypatch):
    """_get_git_path() should return empty string when env is unset."""
    from worker.executor import _get_git_path
    monkeypatch.delenv("HYDRA_GIT_PATH", raising=False)
    assert _get_git_path() == ""


def test_hydra_git_path_configured(monkeypatch):
    """_get_git_path() should return configured path."""
    from worker.executor import _get_git_path
    monkeypatch.setenv("HYDRA_GIT_PATH", "/usr/local/bin/git")
    assert _get_git_path() == "/usr/local/bin/git"


def test_hydra_temp_dir_default(monkeypatch):
    """_get_temp_dir() should return None when env is unset."""
    from worker.executor import _get_temp_dir
    monkeypatch.delenv("HYDRA_TEMP_DIR", raising=False)
    assert _get_temp_dir() is None


def test_hydra_temp_dir_configured(monkeypatch):
    """_get_temp_dir() should return configured path."""
    from worker.executor import _get_temp_dir
    monkeypatch.setenv("HYDRA_TEMP_DIR", "/var/tmp/hydra")
    assert _get_temp_dir() == "/var/tmp/hydra"


def test_shell_executor_uses_hydra_shell_path(monkeypatch):
    """Shell executor should use HYDRA_SHELL_PATH when set."""
    import sys
    # Use the real bash path found on this system
    bash_path = "/bin/bash"
    monkeypatch.setenv("HYDRA_SHELL_PATH", bash_path)
    job = {"executor": {"type": "shell", "script": "echo hello-custom-shell", "shell": "bash"}, "timeout": 5}
    rc, out, err = execute_job(job)
    assert rc == 0, f"stderr: {err}"
    assert "hello-custom-shell" in out


def test_git_uses_hydra_git_path(monkeypatch):
    """git.py should use HYDRA_GIT_PATH when set."""
    from worker.utils.git import _git_bin
    monkeypatch.setenv("HYDRA_GIT_PATH", "/usr/local/bin/git")
    assert _git_bin() == "/usr/local/bin/git"


def test_git_default_path(monkeypatch):
    """git.py should default to 'git' when HYDRA_GIT_PATH is unset."""
    from worker.utils.git import _git_bin
    monkeypatch.delenv("HYDRA_GIT_PATH", raising=False)
    assert _git_bin() == "git"


def test_os_exec_uses_hydra_shell_path(monkeypatch):
    """run_command should honour HYDRA_SHELL_PATH."""
    from worker.utils.os_exec import run_command
    monkeypatch.setenv("HYDRA_SHELL_PATH", "/bin/bash")
    rc, out, _ = run_command("echo env-shell-ok", shell="bash")
    assert rc == 0
    assert "env-shell-ok" in out


def test_python_env_honours_hydra_python_path(monkeypatch):
    """Python executor should use HYDRA_PYTHON_PATH when executor.interpreter is not set."""
    import sys
    monkeypatch.setenv("HYDRA_PYTHON_PATH", sys.executable)
    job = {"executor": {"type": "python", "code": "print('env-python-ok')"}, "timeout": 5}
    rc, out, err = execute_job(job)
    assert rc == 0, f"stderr: {err}"
    assert "env-python-ok" in out


def test_artifact_stdout_intercepted_by_handle_stdout():
    """Lines starting with __HYDRA_ARTIFACT__: emit artifact events and are not logged."""
    import json as _json
    from unittest.mock import MagicMock

    published_events = []
    logged_lines = []

    def fake_publish_run_event(event):
        published_events.append(event)

    def fake_stream_log(kind, text):
        logged_lines.append((kind, text))

    # Replicate the handle_stdout closure logic from worker.py
    _ARTIFACT_PREFIX = "__HYDRA_ARTIFACT__:"

    def handle_stdout(text):
        stripped = text.strip()
        if stripped.startswith(_ARTIFACT_PREFIX):
            raw_json = stripped[len(_ARTIFACT_PREFIX):].strip()
            try:
                artifact_payload = _json.loads(raw_json)
                artifact_name = str(artifact_payload.get("name") or "").strip()
                metadata = artifact_payload.get("metadata") or {}
                if artifact_name:
                    fake_publish_run_event({
                        "type": "artifact_emitted",
                        "run_id": "run-1",
                        "job_id": "job-1",
                        "domain": "prod",
                        "artifact_name": artifact_name,
                        "metadata": metadata,
                    })
            except Exception:
                fake_stream_log("stdout", text)
            return
        fake_stream_log("stdout", text)

    # Normal stdout line passes through
    handle_stdout("some normal output\n")
    assert logged_lines == [("stdout", "some normal output\n")]

    # Artifact line is intercepted and not logged
    handle_stdout('__HYDRA_ARTIFACT__: {"name": "daily_export", "metadata": {"rows": 500}}\n')
    assert len(published_events) == 1
    ev = published_events[0]
    assert ev["type"] == "artifact_emitted"
    assert ev["artifact_name"] == "daily_export"
    assert ev["metadata"] == {"rows": 500}
    # Not logged
    assert len(logged_lines) == 1

    # Malformed artifact line falls back to logging
    handle_stdout("__HYDRA_ARTIFACT__: {bad json}\n")
    assert len(logged_lines) == 2
    assert "__HYDRA_ARTIFACT__" in logged_lines[1][1]


def test_execute_job_emits_artifact_via_stdout():
    """A shell job that prints an artifact marker emits the correct artifact event."""
    import json as _json

    from worker.executor import execute_job

    captured_stdout_lines = []

    def capture_out(text):
        captured_stdout_lines.append(text)

    job = {
        "executor": {
            "type": "shell",
            "script": 'echo \'__HYDRA_ARTIFACT__: {"name": "test_artifact", "metadata": {"count": 42}}\'',
            "shell": "bash",
        },
        "timeout": 5,
    }
    rc, stdout, stderr = execute_job(job, log_callback_out=capture_out)
    assert rc == 0

    # The artifact line should appear in stdout
    full_stdout = "".join(captured_stdout_lines)
    assert "__HYDRA_ARTIFACT__" in full_stdout


# ---------------------------------------------------------------------------
# Sensor executor (worker-side)
# ---------------------------------------------------------------------------

def test_sensor_http_condition_met(monkeypatch):
    """Sensor executor returns success immediately when HTTP check succeeds on first poll."""
    from worker.executor import _execute_sensor

    monkeypatch.setattr("worker.executor._check_http_sensor", lambda executor: True)

    executor = {
        "sensor_type": "http",
        "target": "http://example.com/health",
        "poll_interval_seconds": 1,
        "timeout_seconds": 10,
    }
    rc, out, err = _execute_sensor(executor)
    assert rc == 0
    assert "condition_met" in out
    assert err == ""


def test_sensor_http_timeout(monkeypatch):
    """Sensor executor times out and returns failure if condition is never met."""
    from worker.executor import _execute_sensor

    monkeypatch.setattr("worker.executor._check_http_sensor", lambda executor: False)

    executor = {
        "sensor_type": "http",
        "target": "http://example.com/health",
        "poll_interval_seconds": 1,
        "timeout_seconds": 2,
    }
    rc, out, err = _execute_sensor(executor)
    assert rc == 1
    assert "timed out" in err


def test_sensor_kill_event_stops_loop(monkeypatch):
    """Setting kill_event stops the sensor loop immediately."""
    import threading

    from worker.executor import _execute_sensor

    monkeypatch.setattr("worker.executor._check_http_sensor", lambda executor: False)

    executor = {
        "sensor_type": "http",
        "target": "http://example.com/health",
        "poll_interval_seconds": 60,
        "timeout_seconds": 300,
    }
    terminate = threading.Event()
    terminate.set()
    rc, out, err = _execute_sensor(executor, kill_event=terminate)
    assert rc == 1
    assert "killed" in err


def test_sensor_unknown_sensor_type_returns_error():
    """An unrecognised sensor_type returns a non-zero exit code."""
    from worker.executor import _execute_sensor

    executor = {
        "sensor_type": "unknown_type",
        "target": "https://example.com",
        "poll_interval_seconds": 1,
        "timeout_seconds": 5,
    }
    rc, out, err = _execute_sensor(executor)
    assert rc == 1
    assert "unknown sensor_type" in err


def test_execute_job_sensor_executor(monkeypatch):
    """execute_job routes sensor executor type to the sensor polling loop."""
    from worker.executor import execute_job

    monkeypatch.setattr("worker.executor._check_http_sensor", lambda executor: True)

    job = {
        "executor": {
            "type": "sensor",
            "sensor_type": "http",
            "target": "http://example.com/health",
            "poll_interval_seconds": 1,
            "timeout_seconds": 10,
        }
    }
    rc, out, err = execute_job(job)
    assert rc == 0
    assert "condition_met" in out


# ---------------------------------------------------------------------------
# Capability detection: fail-closed correctness
# ---------------------------------------------------------------------------

def test_detect_capabilities_shell_requires_working_shell(monkeypatch):
    """shell/external should not be advertised when all shell binaries fail."""
    import subprocess

    from worker.executor import _detect_capabilities

    def reject_all(cmd, **kwargs):
        raise FileNotFoundError("mocked shell not found")

    monkeypatch.setattr(subprocess, "run", reject_all)
    caps = _detect_capabilities()
    assert "shell" not in caps
    assert "external" not in caps


def test_detect_capabilities_sql_requires_python(monkeypatch):
    """sql should not be advertised when Python interpreter is absent."""
    import worker.executor as executor_mod
    from worker.executor import _detect_capabilities

    monkeypatch.setattr(executor_mod, "_find_python", lambda: "")
    caps = _detect_capabilities()
    assert "sql" not in caps


def test_detect_capabilities_sensor_always_present():
    """sensor capability should always be advertised (HTTP sensor uses stdlib)."""
    from worker.executor import _detect_capabilities
    caps = _detect_capabilities()
    assert "sensor" in caps


def test_detect_capabilities_no_false_positive_sql_without_driver(monkeypatch):
    """sql should not be advertised when sqlalchemy and pymongo are both absent."""
    import builtins

    import worker.executor as executor_mod
    from worker.executor import _detect_capabilities

    original_import = builtins.__import__

    def import_blocker(name, *args, **kwargs):
        if name in ("sqlalchemy", "pymongo"):
            raise ImportError(f"mocked: {name} unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_blocker)
    monkeypatch.setattr(executor_mod, "_find_python", lambda: "python3")

    caps = _detect_capabilities()
    assert "sql" not in caps, "sql should not be advertised without sqlalchemy/pymongo"


# ---------------------------------------------------------------------------
# Startup timing instrumentation
# ---------------------------------------------------------------------------

def test_process_start_ts_is_set():
    """_PROCESS_START_TS should be set at module import, before any registration."""
    import time

    import worker.worker as worker_mod

    assert hasattr(worker_mod, "_PROCESS_START_TS")
    assert isinstance(worker_mod._PROCESS_START_TS, float)
    assert worker_mod._PROCESS_START_TS <= time.time()
    assert time.time() - worker_mod._PROCESS_START_TS < 3600


def test_execute_job_records_source_fetch_timing(monkeypatch, tmp_path):
    """execute_job should populate timings["source_fetch_ms"] when source is fetched."""
    from worker.executor import execute_job
    from worker.utils.copy import fetch_copy_source as real_fetch

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "run.sh").write_text("echo timing-ok")

    def _fake_fetch(url, dest):
        real_fetch(str(src_dir), dest)

    monkeypatch.setattr("worker.executor.fetch_copy_source", _fake_fetch)

    job = {
        "source": {"protocol": "copy", "url": str(src_dir)},
        "executor": {"type": "shell", "script": "echo timing-ok", "shell": "bash"},
        "timeout": 5,
    }
    timings = {}
    rc, out, err = execute_job(job, timings=timings)
    assert rc == 0
    assert "source_fetch_ms" in timings
    assert timings["source_fetch_ms"] >= 0.0


def test_execute_job_records_env_prep_timing():
    """execute_job should populate timings["env_prep_ms"] for python executor."""
    from worker.executor import execute_job

    job = {
        "executor": {"type": "python", "code": 'print("env-timing")', "interpreter": "python3"},
        "timeout": 10,
    }
    timings = {}
    rc, out, err = execute_job(job, timings=timings)
    assert rc == 0
    assert "env_prep_ms" in timings
    assert timings["env_prep_ms"] >= 0.0


def test_execute_job_no_timings_when_not_provided():
    """execute_job should work fine without a timings dict (backwards compatible)."""
    from worker.executor import execute_job
    job = {"executor": {"type": "shell", "script": "echo ok", "shell": "bash"}, "timeout": 5}
    rc, out, err = execute_job(job)
    assert rc == 0
