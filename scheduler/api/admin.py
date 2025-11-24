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
        jobs_count = db.job_definitions.count_documents({"domain": d})
        runs_count = db.job_runs.count_documents({"domain": d})
        workers_count = len(list(r.scan_iter(f"workers:{d}:*")))
        result.append(
            {
                "domain": d,
                "display_name": meta.get(d, {}).get("display_name", d),
                "description": meta.get(d, {}).get("description", ""),
                "jobs_count": jobs_count,
                "runs_count": runs_count,
                "workers_count": workers_count,
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


@router.post("/domains/{domain}/token")
def rotate_token(domain: str, request: Request):
    _require_admin(request)
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
