"""Domain-scoped credential endpoints.

These endpoints allow domain token holders to manage their own domain's
credentials. Secrets are write-only: callers can create, update, and delete
credentials, but never read back the encrypted payload or sensitive fields.
"""

from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, HTTPException, Request

from ..models.credentials import CredentialCreate, CredentialReference
from ..mongo_client import get_db
from ..utils.encryption import encrypt_payload

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("/")
def list_domain_credentials(request: Request) -> Dict:
    """List credentials in the caller's domain (metadata only, no secrets)."""
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    docs = list(db.credentials.find({"domain": domain}))
    refs = []
    for doc in docs:
        refs.append(CredentialReference(
            name=doc.get("name", ""),
            domain=doc.get("domain", domain),
            credential_type=doc.get("credential_type", "database"),
            dialect=doc.get("dialect"),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        ).model_dump())
    return {"credentials": refs}


@router.post("/")
def create_domain_credential(payload: CredentialCreate, request: Request):
    """Create a credential scoped to the caller's domain."""
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    existing = db.credentials.find_one({"name": payload.name, "domain": domain})
    if existing:
        raise HTTPException(status_code=409, detail="credential with that name already exists in this domain")
    sensitive = payload.model_dump(exclude={"name", "credential_type", "dialect"})
    encrypted = encrypt_payload(sensitive)
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "_id": f"{domain}:{payload.name}",
        "name": payload.name,
        "domain": domain,
        "credential_type": payload.credential_type,
        "dialect": payload.dialect,
        "encrypted_payload": encrypted,
        "created_at": now,
        "updated_at": now,
    }
    db.credentials.insert_one(doc)
    return {"ok": True, "name": payload.name, "domain": domain}


@router.put("/{name}")
def update_domain_credential(name: str, payload: CredentialCreate, request: Request):
    """Update a credential in the caller's domain (write-only)."""
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    existing = db.credentials.find_one({"name": name, "domain": domain})
    if not existing:
        raise HTTPException(status_code=404, detail="credential not found")
    sensitive = payload.model_dump(exclude={"name", "credential_type", "dialect"})
    encrypted = encrypt_payload(sensitive)
    now = datetime.now(timezone.utc).isoformat()
    db.credentials.update_one(
        {"name": name, "domain": domain},
        {"$set": {
            "credential_type": payload.credential_type,
            "dialect": payload.dialect,
            "encrypted_payload": encrypted,
            "updated_at": now,
        }},
    )
    return {"ok": True, "name": name, "domain": domain}


@router.delete("/{name}")
def delete_domain_credential(name: str, request: Request):
    """Delete a credential from the caller's domain."""
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    result = db.credentials.delete_one({"name": name, "domain": domain})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="credential not found")
    return {"ok": True}
