import hashlib
import secrets
from typing import Dict

from fastapi import APIRouter, HTTPException, Request

from ..mongo_client import get_db
from ..redis_client import get_redis
from ..utils.redis_acl import ensure_worker_acl_user, worker_acl_username

router = APIRouter(prefix="/domain", tags=["domain"])


@router.get("/settings")
def get_domain_settings(request: Request) -> Dict:
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    doc = db.domains.find_one({"domain": domain}) or {}
    return {
        "domain": domain,
        "display_name": doc.get("display_name", domain),
        "description": doc.get("description", ""),
        "worker_redis_acl_user": worker_acl_username(domain),
        "global_lock_limits": doc.get("global_lock_limits") or {},
    }


@router.put("/settings")
def update_domain_settings(payload: Dict, request: Request) -> Dict:
    domain = getattr(request.state, "domain", "prod")
    display_name = (payload.get("display_name") or domain).strip() or domain
    description = (payload.get("description") or "").strip()
    raw_limits = payload.get("global_lock_limits")
    global_lock_limits: Dict[str, int] = {}
    if isinstance(raw_limits, dict):
        for k, v in raw_limits.items():
            try:
                global_lock_limits[str(k)] = max(1, int(v))
            except (TypeError, ValueError):
                pass
    db = get_db()
    db.domains.update_one(
        {"domain": domain},
        {"$set": {"display_name": display_name, "description": description, "global_lock_limits": global_lock_limits}},
        upsert=True,
    )
    return {
        "ok": True,
        "domain": domain,
        "display_name": display_name,
        "description": description,
        "global_lock_limits": global_lock_limits,
    }


@router.post("/token/rotate")
def rotate_domain_token(request: Request) -> Dict:
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    r = get_redis()
    doc = db.domains.find_one({"domain": domain})
    if not doc:
        raise HTTPException(status_code=404, detail="domain not found")
    token = secrets.token_hex(24)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.domains.update_one({"domain": domain}, {"$set": {"token_hash": token_hash}})
    r.set(f"token_hash:{domain}", token_hash)
    r.set(f"token_hash:{token_hash}:domain", domain)
    return {"ok": True, "domain": domain, "token": token}


@router.post("/redis_acl/rotate")
def rotate_domain_redis_acl(request: Request) -> Dict:
    domain = getattr(request.state, "domain", "prod")
    db = get_db()
    doc = db.domains.find_one({"domain": domain})
    if not doc:
        raise HTTPException(status_code=404, detail="domain not found")
    redis_acl = ensure_worker_acl_user(domain)
    db.domains.update_one(
        {"domain": domain},
        {
            "$set": {
                "worker_redis_acl_user": redis_acl.get("username"),
                "worker_redis_acl_password": redis_acl.get("password"),
            }
        },
    )
    return {"ok": True, "domain": domain, "worker_redis_acl": redis_acl}
