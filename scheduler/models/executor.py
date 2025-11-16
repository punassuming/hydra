from typing import Annotated, Dict, List, Optional, Union, Literal

from pydantic import BaseModel, Field


class ExecutorBase(BaseModel):
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    workdir: Optional[str] = None


class PythonEnvironment(BaseModel):
    type: Literal["system", "venv", "uv"] = "system"
    python_version: Optional[str] = None
    venv_path: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    requirements_file: Optional[str] = None


class PythonExecutor(ExecutorBase):
    type: Literal["python"] = "python"
    code: str
    interpreter: str = "python3"
    environment: PythonEnvironment = Field(default_factory=PythonEnvironment)


class ShellExecutor(ExecutorBase):
    type: Literal["shell"] = "shell"
    script: str
    shell: str = "bash"


class BatchExecutor(ExecutorBase):
    type: Literal["batch"] = "batch"
    script: str
    shell: str = "cmd"


class ExternalExecutor(ExecutorBase):
    type: Literal["external"] = "external"
    command: str


ExecutorUnion = Union[PythonExecutor, ShellExecutor, BatchExecutor, ExternalExecutor]
ExecutorConfig = Annotated[ExecutorUnion, Field(discriminator="type")]
