"""Shared startup helpers used by both the API server and the standalone orchestrator.

Extracted from main.py so both entrypoints can perform the same initialization
without creating circular imports.
"""

import hashlib
import os
import secrets

from .mongo_client import get_db
from .redis_client import get_redis
from .utils.logging import setup_logging
from .utils.redis_acl import ensure_worker_acl_user

log = setup_logging("scheduler.startup")


def ensure_admin_token() -> None:
    """Ensure ADMIN_TOKEN is set, generating a random one with a warning if not."""
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        admin_token = secrets.token_hex(24)
        os.environ["ADMIN_TOKEN"] = admin_token
        log.warning(
            "ADMIN_TOKEN not set; generated ephemeral token: %s  "
            "Set ADMIN_TOKEN in production to avoid losing access on restart.",
            admin_token,
        )
    from .utils import auth

    auth.ADMIN_TOKEN = admin_token


def warn_credential_encryption_key() -> None:
    """Warn loudly when CREDENTIAL_ENCRYPTION_KEY is not explicitly set.

    Without an explicit key, the encryption key is derived from ADMIN_TOKEN.
    This means that rotating ADMIN_TOKEN will silently make all stored
    credentials (database URIs, PAT tokens, SMTP passwords) unreadable.
    Set CREDENTIAL_ENCRYPTION_KEY to a stable 32-byte base64-url value in
    production to decouple credential encryption from admin token rotation.

    Generate a key with:
        python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
    """
    if not os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip():
        log.warning(
            "CREDENTIAL_ENCRYPTION_KEY is not set. Credential encryption key is being "
            "derived from ADMIN_TOKEN. IMPORTANT: rotating ADMIN_TOKEN will make all "
            "stored credentials unreadable. Set CREDENTIAL_ENCRYPTION_KEY to a stable "
            "32-byte base64-url value for production use. Generate one with: "
            "python -c \"import secrets,base64; "
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())\""
        )


def ensure_domains_seeded() -> None:
    """Cache existing domain token hashes into Redis; seed a default domain if none exist.

    On first startup (empty MongoDB), seeds a domain using optional env vars:
      SEED_DOMAIN              — domain name to seed (default: "prod")
      SEED_DOMAIN_TOKEN        — API token to use; random if omitted
      SEED_DOMAIN_REDIS_PASSWORD — Redis ACL password to use; random if omitted

    Pre-configuring SEED_DOMAIN_TOKEN and SEED_DOMAIN_REDIS_PASSWORD lets dev
    environments (e.g. docker-compose.dev.yml) wire up workers on first boot
    without any manual provisioning steps.
    """
    r = get_redis()
    db = get_db()
    for doc in db.domains.find({}):
        domain = doc.get("domain")
        token_hash = doc.get("token_hash")
        if not domain or not token_hash:
            continue
        r.sadd("hydra:domains", domain)
        r.set(f"token_hash:{domain}", token_hash)
        r.set(f"token_hash:{token_hash}:domain", domain)
        acl_password = doc.get("worker_redis_acl_password")
        if acl_password:
            try:
                ensure_worker_acl_user(domain, password=acl_password)
            except Exception as exc:
                log.warning("Failed to restore Redis ACL user for domain %s: %s", domain, exc)
        else:
            log.warning(
                "Domain %s has no persisted worker Redis ACL password; rotate ACL once to enable restart-safe recovery.",
                domain,
            )
    if db.domains.count_documents({}) == 0:
        seed_domain = os.getenv("SEED_DOMAIN", "prod").strip() or "prod"
        seed_token = os.getenv("SEED_DOMAIN_TOKEN", "").strip() or secrets.token_hex(24)
        seed_redis_password = os.getenv("SEED_DOMAIN_REDIS_PASSWORD", "").strip() or None
        token_hash = hashlib.sha256(seed_token.encode()).hexdigest()

        acl_password = seed_redis_password
        acl_user = None
        try:
            redis_acl = ensure_worker_acl_user(seed_domain, password=seed_redis_password)
            acl_password = redis_acl.get("password")
            acl_user = redis_acl.get("username")
        except Exception as exc:
            log.warning("Failed to provision Redis ACL for domain %s: %s", seed_domain, exc)

        db.domains.insert_one(
            {
                "domain": seed_domain,
                "display_name": seed_domain.capitalize(),
                "description": "Default domain",
                "token_hash": token_hash,
                "worker_redis_acl_user": acl_user,
                "worker_redis_acl_password": acl_password,
            }
        )
        r.sadd("hydra:domains", seed_domain)
        r.set(f"token_hash:{seed_domain}", token_hash)
        r.set(f"token_hash:{token_hash}:domain", seed_domain)
        log.warning("Seeded default '%s' domain with token: %s", seed_domain, seed_token)
        if acl_password:
            log.info("Redis ACL user '%s' provisioned for domain '%s'.", acl_user or seed_domain, seed_domain)
