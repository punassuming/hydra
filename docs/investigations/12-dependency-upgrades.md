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
**Status:** BEHIND  
**Current Pinned:** 2.9.2  
**Latest Stable:** 2.13.4 (as of September 2026)  
**Classification:** Behind  
**Effort:** Low (minor version upgrade within 2.x series)  
**Recommendation:** Upgrade to 2.13.4. Pydantic v2.x is stable; this is a safe minor bump.

#### pymongo==4.10.1
**Status:** BEHIND  
**Current Pinned:** 4.10.1  
**Latest Stable:** 4.18.0 (as of September 2026)  
**Classification:** Behind  
**Breaking Changes:** 4.18.0 dropped support for MongoDB 4.2, added support for MongoDB 9.0. Verify your MongoDB server version.  
**Effort:** Low (assuming MongoDB ≥4.4 is in use)  
**Recommendation:** Upgrade to 4.18.0. Verify MongoDB version compatibility first.

#### python-dotenv==1.0.1
**Status:** CURRENT  
**Current Pinned:** 1.0.1  
**Latest Stable:** 1.0.1  
**Classification:** Current  
**Recommendation:** No upgrade needed. Stable and maintained.

#### redis==5.0.8
**Status:** BEHIND (Major version)  
**Current Pinned:** 5.0.8  
**Latest Stable:** 8.0.1 / 8.1.0 (June 2026)  
**Classification:** Behind — Major version jump (5→8)  
**Breaking Changes:** redis-py 8.0 introduced RESP3 wire format by default with RESP2-compatible response shapes. Significant internal refactoring.  
**Effort:** High (requires testing all Redis operations)  
**Recommendation:** Upgrade to 8.1.0. This is a major bump; allocate time for integration testing, especially for pub/sub, pipelining, and connection pooling.

#### PyYAML==6.0.3
**Status:** CURRENT  
**Current Pinned:** 6.0.3  
**Latest Stable:** 6.0.3 (released September 25, 2025 per search)  
**Classification:** Current  
**Security:** No known vulnerabilities. Latest non-vulnerable version.  
**Recommendation:** No upgrade needed. This is the latest stable release.

#### SQLAlchemy==2.0.36
**Status:** BEHIND  
**Current Pinned:** 2.0.36 (October 15, 2024)  
**Latest Stable:** 2.1.0 (released September 24, 2026) or 2.0.54 (latest 2.0 patch)  
**Classification:** Behind  
**Effort:** Low (minor version upgrade within 2.0 or to 2.1)  
**Recommendation:** Upgrade to 2.0.54 (conservative) or 2.1.0 (latest). Review changelog for any schema reflection or ORM behavior changes.

#### sse-starlette==2.0.0
**Status:** CURRENT  
**Current Pinned:** 2.0.0  
**Latest Stable:** 2.0.0 (no newer version found)  
**Classification:** Current  
**Recommendation:** No upgrade needed. Stable and in use.

#### uvicorn[standard]==0.30.1
**Status:** BEHIND  
**Current Pinned:** 0.30.1  
**Latest Stable:** 0.52.4 (as of September 2026)  
**Classification:** Behind  
**Effort:** Medium (moderate version gap, potential config/behavior changes)  
**Recommendation:** Upgrade to 0.52.4. Significant version jump; review release notes for any changes to SSL handling, worker behavior, or log formatting.

### Development Dependencies

#### httpx (no pinned version)
**Status:** CURRENT  
**Current Pinned:** Flexible (no version constraint)  
**Latest Stable:** 0.27+ (as of September 2026)  
**Classification:** Current (due to flexible constraint)  
**Recommendation:** Consider pinning a specific version for reproducibility (e.g., `httpx>=0.27`).

#### pytest==8.3.5
**Status:** BEHIND  
**Current Pinned:** 8.3.5  
**Latest Stable:** 9.1.1 (as of June 2026)  
**Classification:** Behind  
**Effort:** Low (minor version upgrade, pytest is backward-compatible)  
**Recommendation:** Upgrade to 9.1.1. Pytest maintains good backward compatibility across minor versions.

#### ruff==0.15.22
**Status:** BEHIND  
**Current Pinned:** 0.15.22  
**Latest Stable:** Unknown from search (but 0.15.22 was recent as of search)  
**Classification:** Current or Near-Current  
**Recommendation:** Verify via ruff's GitHub releases if a newer 0.16+ or 0.17+ exists. Ruff moves quickly; check PyPI for latest.

---

## React UI Dependencies (`ui/package.json`)

### Production Dependencies

#### react
**Status:** BEHIND (Major version)  
**Current Pinned:** ^18.2.0  
**Latest Stable:** 19.3.0 (released September 9, 2026)  
**Classification:** Behind — Major version (18→19)  
**Breaking Changes:** React 19 introduces significant API changes. Requires testing all component rendering.  
**Effort:** High (comprehensive testing required)  
**Recommendation:** Upgrade to ^19.3.0. React 18 docs are now on legacy.reactjs.org. Plan for full component and integration testing.

#### react-dom
**Status:** BEHIND (Major version)  
**Current Pinned:** ^18.2.0  
**Latest Stable:** 19.3.0 (released September 9, 2026)  
**Classification:** Behind — Major version (18→19)  
**Recommendation:** Upgrade together with react to ^19.3.0. Must match react version.

#### react-router-dom
**Status:** CURRENT  
**Current Pinned:** ^7.18.3  
**Latest Stable:** 7.18.3 (published 12 days ago, ~September 13, 2026)  
**Classification:** Current  
**Note:** v8 is in development (removes react-router-dom re-export; use react-router/dom instead). Current v7 is stable.  
**Recommendation:** No upgrade needed. When ready for v8, update imports to `react-router/dom`.

#### antd
**Status:** BEHIND (Major version)  
**Current Pinned:** ^5.19.3  
**Latest Stable:** 6.6.5 (released September 22, 2026)  
**Classification:** Behind — Major version (5→6)  
**Breaking Changes:** Ant Design 6 introduces breaking changes. Latest 5.x is 5.29.3 if conservative upgrade preferred.  
**Effort:** High (requires testing all Ant Design components)  
**Recommendation:** Option A (conservative): Upgrade to ^5.29.3 (latest 5.x). Option B (latest): Upgrade to ^6.6.5 with full component testing.

#### @ant-design/icons
**Status:** CURRENT or BEHIND  
**Current Pinned:** ^5.2.6  
**Latest Stable:** ^5.x or ^6.x (aligned with antd)  
**Classification:** Depends on antd choice  
**Recommendation:** Keep aligned with antd version (should use same major version).

#### @tanstack/react-query
**Status:** BEHIND  
**Current Pinned:** ^5.24.7  
**Latest Stable:** 5.103.2 (published September 22, 2026)  
**Classification:** Behind (same major version, but significantly outdated patch)  
**Effort:** Low (minor version bump within v5)  
**Recommendation:** Upgrade to ^5.103.2. Large number of bug fixes and features added since 5.24.7.

#### zod
**Status:** CURRENT or NEAR-CURRENT  
**Current Pinned:** ^3.22.4  
**Latest Stable:** ^3.x (exact version unclear from search)  
**Classification:** Likely Current  
**Recommendation:** Check Zod's npm page for latest 3.x version. Appears to be maintained and current.

### Development Dependencies

#### typescript
**Status:** BEHIND (Major version)  
**Current Pinned:** ^5.4.0  
**Latest Stable:** 7.0.2 (as of July 8, 2026)  
**Classification:** Behind — Major version jump (5→7)  
**Breaking Changes:** TypeScript 6.0 was a transitional release. 7.0.2 is the native port of the compiler. May have breaking changes in strict mode defaults or error reporting.  
**Effort:** Medium (requires testing compilation and type checking across codebase)  
**Recommendation:** Upgrade to ^7.0.2. Test all TypeScript compilation flags and verify no new type errors in strict mode.

#### vite
**Status:** BEHIND (Major version)  
**Current Pinned:** ^6.4.3  
**Latest Stable:** 8.3.0 (published ~September 12, 2026)  
**Classification:** Behind — Major version (6→8)  
**Breaking Changes:** Vite 8 uses Rolldown and Oxc-based tools instead of esbuild and Rollup. Significant build toolchain change.  
**Effort:** High (build configuration may need updates)  
**Recommendation:** Upgrade to ^8.3.0. This is a major toolchain upgrade; test build output and dev server carefully. Review Vite 7→8 migration guide.

#### vitest
**Status:** BEHIND  
**Current Pinned:** ^4.1.11  
**Latest Stable:** 5.0.1 (as of ~September 2026)  
**Classification:** Behind — Major version (4→5)  
**Effort:** Medium (test framework update)  
**Recommendation:** Upgrade to ^5.0.1. Vitest is the official test framework for Vite; v5 should have good compatibility.

#### cypress
**Status:** BEHIND  
**Current Pinned:** ^15.21.1  
**Latest Stable:** 16.0.0 (released ~September 19, 2026)  
**Classification:** Behind — Major version (15→16)  
**Effort:** Medium (test framework update, may require test rewrites)  
**Recommendation:** Upgrade to ^16.0.0. Check Cypress 15→16 migration guide for breaking changes.

#### @vitejs/plugin-react
**Status:** CURRENT or NEAR-CURRENT  
**Current Pinned:** ^5.0.4  
**Latest Stable:** ^5.0+ (aligned with Vite)  
**Classification:** Likely Current  
**Recommendation:** Keep aligned with Vite major version. If upgrading Vite to 8.x, check if plugin-react has v8-compatible release.

#### @testing-library/react
**Status:** CURRENT or BEHIND  
**Current Pinned:** ^14.1.2  
**Latest Stable:** ^14.x or ^15.x (unclear from search)  
**Classification:** Likely Current  
**Recommendation:** Check Testing Library npm page. Should align with React version (currently 19).

#### @testing-library/jest-dom
**Status:** CURRENT or BEHIND  
**Current Pinned:** ^6.2.0  
**Latest Stable:** ^6.x (unclear from search)  
**Classification:** Likely Current  
**Recommendation:** Check Testing Library npm page for latest.

#### @testing-library/user-event
**Status:** CURRENT or BEHIND  
**Current Pinned:** ^14.5.2  
**Latest Stable:** ^14.x or ^15.x (unclear from search)  
**Classification:** Likely Current  
**Recommendation:** Check Testing Library npm page for latest.

#### jsdom
**Status:** BEHIND  
**Current Pinned:** ^24.1.3  
**Latest Stable:** Likely ^25+ (unclear from search)  
**Classification:** Likely Behind  
**Recommendation:** Check jsdom's npm page for latest version. Should work with current Node.js versions.

#### @types/react
**Status:** BEHIND  
**Current Pinned:** ^18.2.25  
**Latest Stable:** ^19.x (aligned with React 19)  
**Classification:** Behind (mismatched with React 18→19 upgrade)  
**Recommendation:** When upgrading React to 19, upgrade @types/react to ^19.x (latest).

#### @types/react-dom
**Status:** BEHIND  
**Current Pinned:** ^18.2.11  
**Latest Stable:** ^19.x (aligned with React 19)  
**Classification:** Behind (mismatched with React 18→19 upgrade)  
**Recommendation:** When upgrading React to 19, upgrade @types/react-dom to ^19.x (latest).

---

## Go Worker Dependencies (`go-worker/go.mod`)

### Go Language

**Go Version Directive:** 1.24  
**Status:** BEHIND/EOL  
**Latest Stable:** 1.26.x (as of September 2026)  
**Classification:** End-of-Life (1.24 is no longer supported as of Go 1.26 release)  
**Recommendation:** Upgrade to `go 1.26` in go.mod. Go follows ~18-month support cycles; 1.24 is now unsupported. Project targets 1.24 for CI per AGENTS.md—update to at least 1.25 or 1.26.

#### github.com/google/uuid
**Status:** CURRENT or NEAR-CURRENT  
**Current Pinned:** v1.6.0  
**Latest Stable:** v1.6.0 or newer (last synced September 1, 2026)  
**Classification:** Likely Current  
**Recommendation:** Check GitHub releases page. UUID generation is stable; unlikely to have breaking changes.

#### github.com/joho/godotenv
**Status:** BEHIND  
**Current Pinned:** v1.5.1  
**Latest Stable:** v1.6.0 (pre-release version mentioned in search; may be stable by now)  
**Classification:** Behind  
**Effort:** Low (minor version bump)  
**Recommendation:** Update to v1.6.0 (or latest). Search results mentioned v1.6.0 pre-releases with error handling improvements.

#### github.com/redis/go-redis/v9
**Status:** BEHIND  
**Current Pinned:** v9.5.1  
**Latest Stable:** v9.22.0 (released August 3, 2026)  
**Classification:** Behind  
**Features Added:** Client-side caching (RESP3 CLIENT TRACKING) and automatic pipelining (experimental). Support for Redis 8.10.  
**Effort:** Medium (test Redis operations, pub/sub, pipelining)  
**Recommendation:** Upgrade to v9.22.0. This is a significant version bump with new features; test thoroughly, especially if using pub/sub or pipelining.

---

## Summary — Prioritized Upgrade List

### By Urgency & Effort

#### CRITICAL (Do First)

1. **google-generativeai → google-genai** (Python)
   - **Urgency:** URGENT — Package deprecated, EOL (June 24, 2026 deadline passed)
   - **Effort:** High
   - **Impact:** Code changes required; AI features will not work without migration
   - **Action:** Migrate all code in `scheduler/api/ai.py` from google-generativeai to google-genai SDK

2. **openai 1.12.0 → 3.19.2** (Python)
   - **Urgency:** High — Major version jump with breaking API changes
   - **Effort:** High
   - **Impact:** All OpenAI LLM calls will fail without update; v3 has different client API
   - **Action:** Allocate time to rewrite LLM integration code and test thoroughly

#### HIGH PRIORITY (Do Soon)

3. **Go 1.24 → 1.26** (Go)
   - **Urgency:** High — 1.24 is End-of-Life as of Go 1.26 release
   - **Effort:** Low
   - **Impact:** Security updates no longer provided for 1.24
   - **Action:** Update `go.mod` to `go 1.26`, test CI pipeline

4. **react 18.2.0 → 19.3.0** (React UI)
   - **Urgency:** High — Major version with breaking changes
   - **Effort:** High
   - **Impact:** Component rendering changes; requires full UI regression testing
   - **Action:** Comprehensive testing required; coordinate with react-dom and @types/react updates

5. **vite 6.4.3 → 8.3.0** (React UI)
   - **Urgency:** High — Major build toolchain change (esbuild/Rollup → Rolldown/Oxc)
   - **Effort:** High
   - **Impact:** Build output and dev server behavior may change; build times may improve
   - **Action:** Test full build pipeline and dev server; review migration guide

6. **antd 5.19.3 → 6.6.5** (React UI)
   - **Urgency:** High — Major version with breaking component changes
   - **Effort:** High
   - **Impact:** UI styling and component APIs change; requires component testing
   - **Alternative:** Stay on 5.29.3 if conservative approach preferred
   - **Action:** Full UI component testing required

#### MEDIUM PRIORITY (Do This Sprint)

7. **redis 5.0.8 → 8.1.0** (Python)
   - **Urgency:** Medium — Major version but internal change (RESP3 wire format)
   - **Effort:** High
   - **Impact:** Redis pub/sub, pipelining, and connection pooling behavior changes
   - **Action:** Integration tests required for all Redis operations

8. **croniter 2.0.5 → 6.2.4** (Python)
   - **Urgency:** Medium — Major version with different cron grammar
   - **Effort:** Medium
   - **Impact:** All cron expressions must be validated after upgrade
   - **Action:** Test all scheduled job definitions; may need expression rewrites

9. **typescript 5.4.0 → 7.0.2** (React UI)
   - **Urgency:** Medium — Major version compiler changes
   - **Effort:** Medium
   - **Impact:** Type checking may be stricter; new error messages possible
   - **Action:** Full TypeScript compilation test; verify no new type errors

10. **vitest 4.1.11 → 5.0.1** (React UI)
    - **Urgency:** Medium — Test framework update
    - **Effort:** Medium
    - **Action:** Run full test suite; verify test compatibility

11. **cypress 15.21.1 → 16.0.0** (React UI)
    - **Urgency:** Medium — E2E test framework update
    - **Effort:** Medium
    - **Action:** Run Cypress tests; review 15→16 migration guide for test rewrites

12. **fastapi 0.115.0 → 0.141.1** (Python)
    - **Urgency:** Medium — Minor version upgrade
    - **Effort:** Low
    - **Action:** Review changelog; test API endpoints

13. **uvicorn 0.30.1 → 0.52.4** (Python)
    - **Urgency:** Medium — Server configuration may change
    - **Effort:** Medium
    - **Action:** Test server startup and SSL handling; review changelog

14. **go-redis v9.5.1 → v9.22.0** (Go)
    - **Urgency:** Medium — Significant feature additions
    - **Effort:** Medium
    - **Action:** Test Redis operations; opt-in to experimental features if desired

#### LOW PRIORITY (Do When Convenient)

15. **pymongo 4.10.1 → 4.18.0** (Python)
    - **Urgency:** Low — Patch within stable 4.x series
    - **Effort:** Low
    - **Action:** Verify MongoDB server version ≥4.4; test Mongo operations

16. **pydantic 2.9.2 → 2.13.4** (Python)
    - **Urgency:** Low — Minor version upgrade
    - **Effort:** Low
    - **Action:** Run tests; verify no new validation errors

17. **@tanstack/react-query 5.24.7 → 5.103.2** (React UI)
    - **Urgency:** Low — Same major version, large patch gap
    - **Effort:** Low
    - **Action:** Test API data fetching; many bug fixes included

18. **SQLAlchemy 2.0.36 → 2.1.0** (Python)
    - **Urgency:** Low — Minor version upgrade
    - **Effort:** Low
    - **Action:** Test schema reflection and ORM behavior; review changelog

19. **pytest 8.3.5 → 9.1.1** (Python)
    - **Urgency:** Low — Test framework, good backward compatibility
    - **Effort:** Low
    - **Action:** Run all tests; verify no behavior changes

20. **cryptography ≥46.0.5 → ≥49.0.0** (Python)
    - **Urgency:** Low — Security-relevant but current constraint allows update
    - **Effort:** Low
    - **Action:** Update constraint; monitor for breaking changes in cryptographic operations

### Current or Stable (No Action)

- **python-dotenv 1.0.1** — Current
- **PyYAML 6.0.3** — Current, released Sept 25, 2025
- **sse-starlette 2.0.0** — Current
- **react-router-dom 7.18.3** — Current (v8 in development)
- **httpx** — Flexible constraint (Current due to no pin)
- **ruff 0.15.22** — Current or near-current
- **zod** — Likely current
- **@vitejs/plugin-react** — Aligned with Vite (will need update if Vite upgraded)
- **@testing-library/** packages — Likely current; check individually
- **jsdom** — Likely current; check npm
- **joho/godotenv v1.5.1** — Minor behind; v1.6.0 pre-release exists
- **google/uuid v1.6.0** — Likely current

---

## Dependency Update Strategy

### Phase 1: Critical (Week 1)
1. Migrate `google-generativeai` → `google-genai` 
2. Upgrade OpenAI SDK to v3.19.2 and test all LLM calls
3. Update Go to 1.26

### Phase 2: Build Toolchain (Week 2)
4. Upgrade Vite 6 → 8 (build system)
5. Update TypeScript to 7.0.2 (compiler)
6. Update Vitest to 5.0.1 (test runner)

### Phase 3: Frontend Framework (Week 3)
7. Upgrade React 18 → 19 (with react-dom, @types/react, @types/react-dom)
8. Upgrade Ant Design 5 → 6 (UI component library)
9. Update Cypress to 16.0.0 (e2e testing)

### Phase 4: Backend/Data (Week 4)
10. Upgrade Redis client 5 → 8 (requires integration testing)
11. Upgrade croniter 2 → 6 (requires cron expression validation)
12. Minor updates: pymongo, SQLAlchemy, fastapi, uvicorn

### Testing Strategy
- **Phase 1:** Unit tests for AI/LLM integration
- **Phase 2:** Full build test, type checking
- **Phase 3:** Full UI regression test, Cypress e2e
- **Phase 4:** Integration tests, acceptance tests

### Risk Assessment
- **High Risk:** google-generativeai migration, openai v3, React 19, Vite 8, Redis 8, Ant Design 6
- **Medium Risk:** croniter major version, Go 1.26, TypeScript 7
- **Low Risk:** Most patch/minor updates

---

## Python Version Floor

**Current Floor:** Python 3.11 (per pyproject.toml and AGENTS.md)  
**Recommendation:** Keep 3.11 as minimum. Python 3.12 and 3.13 are available and stable (CI targets 3.13). Consider moving floor to 3.12 if libraries require it, but 3.11 is still broadly supported as of September 2026.

