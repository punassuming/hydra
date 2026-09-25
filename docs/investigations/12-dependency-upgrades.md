# Dependency Audit: Hydra Jobs Ecosystem Upgrades

**Date:** 2026-09-25  
**Scope:** Python (`pyproject.toml`), React UI (`ui/package.json`), Go Worker (`go-worker/go.mod`)

---

## Python Dependencies (`pyproject.toml`)

### Production Dependencies

#### croniter==2.0.5
**Status:** PENDING  
**Current Pinned:** 2.0.5

#### cryptography>=46.0.5
**Status:** PENDING  
**Current Pinned:** >=46.0.5

#### fastapi==0.115.0
**Status:** PENDING  
**Current Pinned:** 0.115.0

#### google-generativeai==0.3.2
**Status:** PENDING  
**Current Pinned:** 0.3.2  
**Note:** Already known-deprecated per AGENTS.md investigation lesson. Will verify status.

#### openai==1.12.0
**Status:** PENDING  
**Current Pinned:** 1.12.0

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

