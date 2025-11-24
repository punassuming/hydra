from fastapi import APIRouter, Request, HTTPException
from typing import List, Dict
import secrets
import hashlib
from ..redis_client import get_redis
from ..mongo_client import get_db
from ..utils.auth import _hash_token

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request):
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="admin only")


@router.get("/domains")
def list_domains(request: Request) -> Dict[str, List[Dict]]:
    _require_admin(request)
    r = get_redis()
    db = get_db()
    domains = list(r.smembers("hydra:domains") or [])
    meta = {doc["domain"]: doc for doc in db.domains.find({})}
    result = []
    for d in domains:
        result.append(
            {
                "domain": d,
                "display_name": meta.get(d, {}).get("display_name", d),
                "description": meta.get(d, {}).get("description", ""),
            }
        )
    return {"domains": result}


@router.post("/domains")
def create_domain(payload: Dict, request: Request):
    _require_admin(request)
    domain = (payload.get("domain") or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="domain required")
    display = payload.get("display_name") or domain
    desc = payload.get("description") or ""
    token = payload.get("token") or secrets.token_hex(24)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    r = get_redis()
    db = get_db()
    r.sadd("hydra:domains", domain)
    db.domains.update_one(
        {"domain": domain},
        {"$set": {"display_name": display, "description": desc, "token_hash": token_hash}},
        upsert=True,
    )
    # cache token hash for fast lookup
    r.setex(f"token_hash:{token_hash}:domain", 300, domain)
    return {"ok": True, "domain": domain, "token": token}


@router.put("/domains/{domain}")
def rename_domain(domain: str, payload: Dict, request: Request):
    """
    Lightweight rename updates display metadata only (does not move data).
    """
    _require_admin(request)
    display = payload.get("display_name") or domain
    desc = payload.get("description") or ""
    token = payload.get("token")
    token_hash = hashlib.sha256(token.encode()).hexdigest() if token else None
    db = get_db()
    update = {"display_name": display, "description": desc}
    if token_hash:
        update["token_hash"] = token_hash
    db.domains.update_one({"domain": domain}, {"$set": update}, upsert=True)
    if token_hash:
        r = get_redis()
        r.setex(f"token_hash:{token_hash}:domain", 300, domain)
    return {"ok": True, "domain": domain, "token": token if token else None}


@router.delete("/domains/{domain}")
def delete_domain(domain: str, request: Request):
    _require_admin(request)
    db = get_db()
    r = get_redis()
    db.domains.delete_one({"domain": domain})
    r.srem("hydra:domains", domain)
    # clear token cache
    token_hash = r.get(f"token_hash:{domain}")
    if token_hash:
        r.delete(f"token_hash:{token_hash}:domain")
    r.delete(f"token_hash:{domain}")
    return {"ok": True}
