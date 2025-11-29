import os
import platform
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple, Callable


def _venv_python_path(venv_dir: str) -> str:
    if platform.system().lower().startswith("win"):
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _run(cmd: List[str]):
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _install_requirements(python_bin: str, requirements: List[str], requirements_file: Optional[str]):
    if requirements:
        _run([python_bin, "-m", "pip", "install", *requirements])
    if requirements_file:
        _run([python_bin, "-m", "pip", "install", "-r", requirements_file])


def _resolve_python_binary(version: Optional[str], default: str) -> str:
    if not version:
        return default
    version = version.strip()
    if not version:
        return default
    if version.startswith("python"):
        return version
    return f"python{version}"


def prepare_python_command(executor: Dict, job_id: str) -> Tuple[List[str], Optional[Callable[[], None]]]:
    env_cfg = (executor.get("environment") or {})
    env_type = env_cfg.get("type", "system")
    python_version = env_cfg.get("python_version")
    interpreter = executor.get("interpreter", "python3")
    requirements = env_cfg.get("requirements") or []
    requirements_file = env_cfg.get("requirements_file") or None
    venv_path = env_cfg.get("venv_path") or None
    cleanup = None

    if env_type == "uv":
        cmd = ["uv", "run"]
        if python_version:
            cmd += ["--python", python_version]
        for req in requirements:
            cmd += ["--with", req]
        if requirements_file:
            cmd += ["--requirements", requirements_file]
        cmd += [interpreter]
        return cmd, cleanup

    # Enforce venv for all non-uv execution to ensure isolation
    # "system" type now means "use system python to create a venv"
    if venv_path:
        python_bin = _venv_python_path(venv_path)
    else:
        base_python = _resolve_python_binary(python_version, interpreter)
        tmp_dir = tempfile.mkdtemp(prefix=f"hydra-venv-{job_id}-")
        _run([base_python, "-m", "venv", tmp_dir])
        python_bin = _venv_python_path(tmp_dir)

        def _cleanup():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        cleanup = _cleanup
    
    if requirements or requirements_file:
        _install_requirements(python_bin, requirements, requirements_file)
    return [python_bin], cleanup
