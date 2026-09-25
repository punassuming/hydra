# Dependency Audit: Hydra Jobs Ecosystem Upgrades

**Date:** 2026-09-25  
**Scope:** Python (`pyproject.toml`), React UI (`ui/package.json`), Go Worker (`go-worker/go.mod`)

---

## Python Dependencies (`pyproject.toml`)

### Production Dependencies

#### croniter==2.0.5
**Status:** BEHIND (Major version jump)  
**Current Pinned:** 2.0.5  
**Latest Stable:** 6.2.4 (as of July 2026)  
**Classification:** Behind  
**Breaking Changes:** Major version jump from 2.0.5 → 6.2.4. Versions 2 and 6 have different cron grammar implementations. Requires compatibility testing.  
**Effort:** Medium (may need to test cron expressions)  
**Recommendation:** Upgrade to 6.2.4 as part of a larger compatibility review. Validate all cron schedule expressions after upgrade.

#### cryptography>=46.0.5
**Status:** BEHIND  
**Current Pinned:** >=46.0.5 (flexible constraint)  
**Latest Stable:** 49.0.0  
**Classification:** Behind  
**Security Notes:** 46.0.5 (Feb 10, 2026) fixed CVE-2026-26007 (binary elliptic curve attack). Current constraint allows upgrade. No newer CVEs noted for 49.0.0.  
**Effort:** Low (minor version upgrade)  
**Recommendation:** Update constraint to `>=49.0.0` or `>=49.0` if testing confirms no breaking changes. Security-sensitive: review changelog for any OpenSSL/cryptography algorithm changes.

#### fastapi==0.115.0
**Status:** BEHIND  
**Current Pinned:** 0.115.0  
**Latest Stable:** 0.141.1 (as of July 29, 2026)  
**Classification:** Behind  
**Effort:** Low (minor version upgrade within 0.x series)  
**Recommendation:** Upgrade to 0.141.1. Review changelog for any deprecated parameters or middleware changes.

#### google-generativeai==0.3.2
**Status:** DEPRECATED/EOL (URGENT)  
**Current Pinned:** 0.3.2  
**Replacement Package:** `google-genai` (new unified Google GenAI SDK)  
**Classification:** Deprecated/EOL — Urgent Migration Required  
**Details:** Google has officially deprecated the google-generativeai package. The package emits FutureWarning on every import and is no longer receiving updates or bug fixes. Google Vertex AI SDK migration deadline was June 24, 2026 (already passed).  
**Effort:** High (requires code changes to migrate from google-generativeai to google-genai)  
**Recommendation:** URGENT. Migrate to `google-genai` package immediately. This is a breaking change that requires rewriting the AI integration code in `scheduler/api/ai.py`.

#### openai==1.12.0
**Status:** BEHIND (Critical — Major version)  
**Current Pinned:** 1.12.0  
**Latest Stable:** 3.19.2 (as of September 24, 2026)  
**Classification:** Behind — Major version jump (1.x → 3.x)  
**Breaking Changes:** Significant version jump. OpenAI SDK v3.x has breaking changes compared to v1.12.0. Likely requires rewriting calls in `scheduler/api/ai.py`.  
**Effort:** High (requires testing all OpenAI integration code)  
**Recommendation:** Upgrade to 3.19.2, but allocate time for thorough testing of all LLM calls. Review OpenAI SDK changelog for v2.0 and v3.0 breaking changes.

#### pydantic==2.9.2
**Status:** PENDING  
**Current Pinned:** 2.9.2

#### pymongo==4.10.1
**Status:** PENDING  
**Current Pinned:** 4.10.1

#### python-dotenv==1.0.1
**Status:** PENDING  
**Current Pinned:** 1.0.1

#### redis==5.0.8
**Status:** PENDING  
**Current Pinned:** 5.0.8

#### PyYAML==6.0.3
**Status:** PENDING  
**Current Pinned:** 6.0.3

#### SQLAlchemy==2.0.36
**Status:** PENDING  
**Current Pinned:** 2.0.36

#### sse-starlette==2.0.0
**Status:** PENDING  
**Current Pinned:** 2.0.0

#### uvicorn[standard]==0.30.1
**Status:** PENDING  
**Current Pinned:** 0.30.1

### Development Dependencies

#### httpx (no pinned version)
**Status:** PENDING

#### pytest==8.3.5
**Status:** PENDING  
**Current Pinned:** 8.3.5

#### ruff==0.15.22
**Status:** PENDING  
**Current Pinned:** 0.15.22

---

## React UI Dependencies (`ui/package.json`)

### Production Dependencies

#### react
**Status:** PENDING  
**Current Pinned:** ^18.2.0

#### react-dom
**Status:** PENDING  
**Current Pinned:** ^18.2.0

#### react-router-dom
**Status:** PENDING  
**Current Pinned:** ^7.18.3  
**Note:** Recently bumped to v7 per AGENTS.md — verify if 7.18.3 is current.

#### antd
**Status:** PENDING  
**Current Pinned:** ^5.19.3

#### @ant-design/icons
**Status:** PENDING  
**Current Pinned:** ^5.2.6

#### @tanstack/react-query
**Status:** PENDING  
**Current Pinned:** ^5.24.7

#### zod
**Status:** PENDING  
**Current Pinned:** ^3.22.4

### Development Dependencies

#### typescript
**Status:** PENDING  
**Current Pinned:** ^5.4.0

#### vite
**Status:** PENDING  
**Current Pinned:** ^6.4.3  
**Note:** Recently bumped to v6 per AGENTS.md — verify if 6.4.3 is current.

#### vitest
**Status:** PENDING  
**Current Pinned:** ^4.1.11  
**Note:** Recently bumped to v4 per AGENTS.md — verify if 4.1.11 is current.

#### cypress
**Status:** PENDING  
**Current Pinned:** ^15.21.1  
**Note:** Recently bumped to v15 per AGENTS.md — verify if 15.21.1 is current.

#### @vitejs/plugin-react
**Status:** PENDING  
**Current Pinned:** ^5.0.4

#### @testing-library/react
**Status:** PENDING  
**Current Pinned:** ^14.1.2

#### @testing-library/jest-dom
**Status:** PENDING  
**Current Pinned:** ^6.2.0

#### @testing-library/user-event
**Status:** PENDING  
**Current Pinned:** ^14.5.2

#### jsdom
**Status:** PENDING  
**Current Pinned:** ^24.1.3

#### @types/react
**Status:** PENDING  
**Current Pinned:** ^18.2.25

#### @types/react-dom
**Status:** PENDING  
**Current Pinned:** ^18.2.11

---

## Go Worker Dependencies (`go-worker/go.mod`)

### Go Language

**Go Version Directive:** 1.24

#### github.com/google/uuid
**Status:** PENDING  
**Current Pinned:** v1.6.0

#### github.com/joho/godotenv
**Status:** PENDING  
**Current Pinned:** v1.5.1

#### github.com/redis/go-redis/v9
**Status:** PENDING  
**Current Pinned:** v9.5.1

---

## Summary — Prioritized Upgrade List

*To be populated as investigation completes.*

