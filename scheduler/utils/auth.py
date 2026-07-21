import hashlib
import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse

from ..mongo_client import get_db
from ..redis_client import get_redis

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
ADMIN_DOMAIN = os.getenv("ADMIN_DOMAIN", "admin")


def _is_allowed_path(path: str) -> bool:
    return path.startswith("/health")


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("x-api-key") or request.headers.get("authorization", "").replace("Bearer ", "").strip()
    if header:
        return header
    token_qs = request.query_params.get("token")
    if token_qs:
        return token_qs
    return None


def _extract_domain(request: Request) -> str | None:
    header_domain = (request.headers.get("x-domain") or "").strip()
    if header_domain:
        return header_domain
    query_domain = (request.query_params.get("domain") or "").strip()
    if query_domain:
        return query_domain
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_domain_token_hash(domain: str) -> str | None:
    r = get_redis()
    cached = r.get(f"token_hash:{domain}")
    if cached:
        return cached
    db = get_db()
    doc = db.domains.find_one({"domain": domain})
    if doc:
        token_hash = doc.get("token_hash")
        if token_hash:
            r.set(f"token_hash:{domain}", token_hash)
            r.set(f"token_hash:{token_hash}:domain", domain)
            return token_hash
    return None


def _validate_domain_token(domain: str, token: str) -> str | None:
    expected_hash = get_domain_token_hash(domain)
    if not expected_hash:
        return None
    provided_hash = _hash_token(token)
    if hmac.compare_digest(expected_hash, provided_hash):
        return provided_hash
    return None


def _unauthorized_response(detail: str = "unauthorized") -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


async def enforce_api_key(request: Request, call_next):
    # Allow CORS preflight without auth
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    token = _extract_token(request)
    req_domain = _extract_domain(request)
    admin_token = ADMIN_TOKEN or os.getenv("ADMIN_TOKEN")

    # Admin token short-circuit (respect ?domain override for observation)
    if admin_token and hmac.compare_digest(token or "", admin_token):
        request.state.domain = req_domain or ADMIN_DOMAIN
        request.state.is_admin = True
        return await call_next(request)

    if _is_allowed_path(request.url.path):
        return await call_next(request)

    if not token:
        return _unauthorized_response()

    if not req_domain:
        return _unauthorized_response("domain required")

    token_hash = _validate_domain_token(req_domain, token)
    if not token_hash:
        return _unauthorized_response()

    request.state.domain = req_domain
    request.state.is_admin = False
    request.state.token_hash = token_hash
    return await call_next(request)
