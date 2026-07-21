from typing import Literal, Optional

from pydantic import BaseModel, Field


class CredentialCreate(BaseModel):
    name: str
    credential_type: Literal["database", "api_key", "generic"] = "database"
    dialect: Optional[str] = None
    connection_uri: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    extra: Optional[dict] = Field(default_factory=dict)


class CredentialStored(BaseModel):
    name: str
    domain: str = "prod"
    credential_type: str = "database"
    dialect: Optional[str] = None
    encrypted_payload: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CredentialReference(BaseModel):
    name: str
    domain: str = "prod"
    credential_type: str
    dialect: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
