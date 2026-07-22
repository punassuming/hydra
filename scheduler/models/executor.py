from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class KerberosConfig(BaseModel):
    principal: str
    keytab: str
    ccache: Optional[str] = None


class ExecutorBase(BaseModel):
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    workdir: Optional[str] = None
    impersonate_user: Optional[str] = None
    kerberos: Optional[KerberosConfig] = None


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


class PowerShellExecutor(ExecutorBase):
    type: Literal["powershell"] = "powershell"
    script: str
    shell: str = "pwsh"


class SqlExecutor(ExecutorBase):
    type: Literal["sql"] = "sql"
    dialect: Literal["postgres", "mysql", "mssql", "oracle", "mongodb"] = "postgres"
    connection_uri: Optional[str] = None
    credential_ref: Optional[str] = None
    query: str
    database: Optional[str] = None
    max_rows: int = Field(default=10000, ge=1, le=100000)
    autocommit: bool = True


class HttpExecutor(ExecutorBase):
    type: Literal["http"] = "http"
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET"
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    expected_status: List[int] = Field(default=[200])
    timeout_seconds: int = 30
    credential_ref: Optional[str] = None


class ExternalExecutor(ExecutorBase):
    type: Literal["external"] = "external"
    command: str


class SensorExecutor(ExecutorBase):
    type: Literal["sensor"] = "sensor"
    sensor_type: Literal["http", "sql"] = "http"
    target: str
    poll_interval_seconds: int = Field(default=30, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)
    # HTTP-specific
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    expected_status: List[int] = Field(default_factory=lambda: [200])
    # SQL-specific
    dialect: Literal["postgres", "mysql", "mssql", "oracle", "mongodb"] = "postgres"
    connection_uri: Optional[str] = None
    # Shared
    credential_ref: Optional[str] = None


ExecutorUnion = Union[
    PythonExecutor,
    ShellExecutor,
    BatchExecutor,
    PowerShellExecutor,
    SqlExecutor,
    HttpExecutor,
    ExternalExecutor,
    SensorExecutor,
]
ExecutorConfig = Annotated[ExecutorUnion, Field(discriminator="type")]
