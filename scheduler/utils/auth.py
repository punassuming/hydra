import os
import hashlib
from fastapi import Request, HTTPException
from ..mongo_client import get_db
from ..redis_client import get_redis


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
ADMIN_DOMAIN = os.getenv("ADMIN_DOMAIN", "admin")


def _is_allowed_path(path: str) -> bool:
    return path.startswith("/health") or path.startswith("/events/stream")


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("x-api-key") or request.headers.get("authorization", "").replace("Bearer ", "").strip()
    if header:
        return header
    token_qs = request.query_params.get("token")
    if token_qs:
        return token_qs
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _lookup_domain_by_token(token: str) -> tuple[str | None, str | None]:
    """
    Returns (domain, token_hash) if found, else (None, None)
    """
    h = _hash_token(token)
    r = get_redis()
    # try redis cache
    dom = r.get(f"token_hash:{h}:domain")
    if dom:
        return dom, h
    db = get_db()
    doc = db.domains.find_one({"token_hash": h})
    if doc:
        domain = doc.get("domain")
        r.setex(f"token_hash:{h}:domain", 300, domain)
        return domain, h
    return None, None


async def enforce_api_key(request: Request, call_next):
    # Allow CORS preflight without auth
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    token = _extract_token(request)
    admin_token = ADMIN_TOKEN or os.getenv("ADMIN_TOKEN")

    # Admin token short-circuit (respect ?domain override for observation)
    if token == admin_token:
        req_domain = request.query_params.get("domain") or ADMIN_DOMAIN
        request.state.domain = req_domain
        request.state.is_admin = True
        return await call_next(request)

    if _is_allowed_path(request.url.path):
        # Best-effort: if a domain token is present, attach it
        if token:
            domain, token_hash = _lookup_domain_by_token(token)
            if domain:
                request.state.domain = domain
                request.state.is_admin = False
                request.state.token_hash = token_hash
            else:
                # If admin token missing but provided, allow admin view passthrough
                request.state.domain = ADMIN_DOMAIN
                request.state.is_admin = True
        return await call_next(request)

    if not token:
        raise HTTPException(status_code=401, detail="unauthorized")

    domain, token_hash = _lookup_domain_by_token(token)
    if not domain:
        raise HTTPException(status_code=401, detail="unauthorized")

    request.state.domain = domain
    request.state.is_admin = False
    request.state.token_hash = token_hash
    return await call_next(request)
