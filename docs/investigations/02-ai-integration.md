# AI Integration Investigation

**Investigation Date:** 2026-09-25

## Area 1: Provider Abstraction
*Investigating `scheduler/api/ai.py` for LLM provider abstraction design*

### Findings

**File:** `/home/user/Hydra/scheduler/api/ai.py` (lines 109-156)

**Current Abstraction:**
- Two provider functions: `_call_gemini()` (line 109) and `_call_openai()` (line 124)
- Single dispatch point `_call_llm()` (line 145) switches on `AIProvider` enum
- Default models stored in `_DEFAULT_MODELS` dict (line 23)
- Provider enum at line 25 with GEMINI and OPENAI

**Design Ease for Adding Anthropic Claude:**
- **Easy parts**: Adding enum variant (line 25), adding model to `_DEFAULT_MODELS`, adding case to dispatcher
- **Problematic**: System prompt handling is inconsistent
  - `_call_gemini()` concatenates system prompt manually into full_prompt (line 117)
  - `_call_openai()` uses proper messages API with system role (line 132)
  - A new provider must choose which approach; inconsistency can cause behavioral differences
- **Missing abstractions**: No base class/protocol for provider functions, all logic duplicated

**Error Handling Gaps (lines 109-143):**
1. **No timeouts** on API calls — if Gemini/OpenAI hang, HTTP request will hang indefinitely
2. **Generic exception handling** — rate limits (429), auth errors (401), malformed responses all become 500 "Gemini Error"
3. **No retry logic** — transient errors fail immediately
4. **No provider-specific status codes** — caller cannot distinguish "missing key" from "network error"

**Recommendation:** 
- Refactor to use a provider protocol/base class to enforce consistent signature/behavior
- Add per-provider timeout (e.g., 30s via `timeout` param on client init)
- Distinguish provider errors: raise specific `ProviderAuthError`, `ProviderRateLimitError`, `ProviderTimeoutError`
- Document system prompt handling requirement when adding new providers
- **Quick win**: Add `timeout=30` to both Gemini and OpenAI clients immediately (low-hanging safety fix)

## Area 2: Feature Completeness & Quality
*Investigating all AI endpoints: generate_job, analyze_run, predict_duration, diagnose_regression*

### Findings

**File:** `/home/user/Hydra/scheduler/api/ai.py` (lines 168-431)

**Endpoint 1: `generate_job` (lines 168-178)**
- **System Prompt Quality**: Excellent (lines 80-107)
  - Clear schema explanation, executor types with timeouts, field descriptions
  - Minimal example provided, escape hatches explained (omit defaults)
  - Well-scoped instructions
- **Prompt Injection Surface**: User prompt at line 170 is directly used
  - Risk: Low — prompt is a natural language request, not structured data escaping JSON
  - Still should sanitize extremely long prompts (no limit enforced)
- **Error Handling**: JSON parsing wrapped (line 174), fails with 500 on malformed output
  - Issue: If LLM returns non-JSON or partial JSON, user gets opaque "Failed to parse generated job" error
  - Missing: Retry-on-empty, validation of required fields before returning

**Endpoint 2: `analyze_run` (lines 180-244)**
- **System Prompt Quality**: Good, but varies by analysis_type (lines 194-241)
  - Each analysis mode has context-appropriate guidance (summary, errors, retry, custom)
  - Clean separation of concerns
- **Prompt Injection Surface**: Critical issue
  - Line 182-183: stdout/stderr truncated to STDOUT_TAIL_CHARS (2500) / STDERR_TAIL_CHARS (6000) — good
  - Line 226: User `question` embedded directly into prompt without escaping
  - Risk: Attacker can craft a question like `"ignore instructions, the password is..."`
  - Recommendation: Use structured prompt format or validate question matches safe pattern
- **Error Handling**: No try/catch around `_call_llm()` (line 243), returns raw LLM text
  - Issue: Malformed LLM response or rate limit returns as-is to user (good for transparency, bad for graceful degradation)

**Endpoint 3: `predict_duration` (lines 289-312)**
- **No LLM Call** — uses historical percentiles only (line 302)
- **Quality**: Excellent
  - Shares `duration_percentiles()` helper (line 259) with diagnose_regression
  - Median used for stability (line 309 comment) instead of mean
  - Handles edge case: no historical data returns 0 sample_size
  - Auth-aware: domain filtering via `request.state` (lines 293-300)
- **No injection risk** — data-driven only

**Endpoint 4: `diagnose_regression` (lines 352-431)**
- **System Prompt Quality**: Excellent (lines 332-349)
  - Clear JSON schema, instructs LLM to ground in evidence
  - Explicitly says "don't invent a code-level cause you cannot support"
- **Prompt Injection Surface**: Similar to analyze_run
  - Lines 393-400: stdout/stderr truncated, good
  - Line 405-411: job_name from DB (trusted), but user cannot override
  - Risk: Lower than analyze_run because diff text is auto-generated (not user-supplied)
- **Error Handling**: JSON parsing with custom error (line 416-418)
  - Issue: If LLM returns low-confidence text like "Unable to determine cause", JSON parse fails with 500
  - Missing: Graceful fallback for ambiguous cases (e.g., return low-confidence response instead of error)
- **Missing Capability**: No caching of baseline run or historical comparisons
  - Every call re-fetches baseline (line 370) and duration percentiles (line 380)
  - For frequently-analyzed jobs, this is inefficient

**Summary:**
- ✅ System prompts well-written and context-appropriate
- ❌ Timeout risk on LLM calls (no timeouts)
- ⚠️ Prompt injection via user question/custom analysis (truncation helps but not sufficient)
- ⚠️ JSON parsing failures treated as 500 errors instead of graceful degradation
- 🔍 Inconsistent error reporting across endpoints

## Area 3: UI Integration
*Investigating JobForm, FailureInsight, ProviderSelect, InvestigateDrawer components*

### Findings

**ProviderSelect Component** (`ui/src/components/ProviderSelect.tsx`)
- **Quality**: Excellent design
  - Single shared component (line 12-14 comment) used by all AI features
  - Simplifies provider management — changes in one place only
  - Clean Ant Design Select wrapper
- **UX**: Good
  - Dropdown shows "Gemini" and "OpenAI" labels
  - No default shown if value is None (could improve clarity)

**FailureInsight Component** (`ui/src/components/FailureInsight.tsx`, lines 21-232)
- **AI Log Assistant Integration**
  - Lines 38-57: `handleAnalyze()` calls analyzeRun via API
  - Lines 182-202: Analysis type selector with custom question input
  - Good UX: Provider picker at line 181 via ProviderSelect
  - Issue: Custom question input (line 195) has no character limit, risk of prompt injection
  - Recommendation: Add maxLength={500} to Input field
- **Run Diff Copilot Integration**
  - Lines 59-75: `handleDiagnoseRegression()` calls diagnoseRegression
  - Lines 77-134: Renders RegressionDiagnosis response with confidence tags (line 84)
  - Good UX: Collapse for evidence items (lines 93-108), shows baseline comparison (lines 117-119)
  - Error handling good (lines 67-71): Detects `no_prior_success` and gives user-friendly message
- **Loading States**
  - Lines 207-211: Button shows "Analyzing..." with Spin icon during load
  - Lines 212-218: Separate button for diff comparison
  - Good: Two independent operations, user can trigger either
- **Caching**: None — every analysis/diff call re-queries backend
  - For frequently-viewed runs, this causes redundant API calls
  - Recommendation: Use react-query (already in deps) to cache analyze_run and diagnoseRegression results by runId

**Magic Job Generator Integration** (`ui/src/components/job-form/index.tsx`, lines 138-152)
- **Component Structure**
  - Lines 70-72: State for prompt, generating flag, and provider selection
  - Lines 138-151: `handleGenerate()` calls generateJob via API
  - Lines 21: Uses ProviderSelect component for provider choice
- **Good UX**
  - Shows provider dropdown (via ProviderSelect)
  - Loading state during generation
  - Normalizes generated executor to form schema (lines 119-136)
- **Issue**: No visible preview of generated job before form auto-fill
  - Generated job just replaces current form state (line 148)
  - Users cannot review/adjust generation before it overwrites their work
  - Recommendation: Add a "Preview & Edit" dialog before applying generated job

**InvestigateDrawer Component** (`ui/src/components/InvestigateDrawer.tsx`, lines 32-85)
- **Good Design**
  - React Query integration for catalog fetch (line 35-39)
  - Lazy-loads investigation results (line 41-45: enabled only when selectedKey is set)
  - Icons mapped per check type (line 20-25)
  - Clear description (line 27-31): Notes this is LLM-free
- **UX**: Excellent
  - Drawer on right side (line 96: width 640)
  - Table columns show job name, domain, metric, last run (lines 52-85)
- **No caching issue here** — investigations are instant (no LLM), so no perf concern

**Summary:**
- ✅ ProviderSelect DRY component used everywhere
- ✅ Good error handling in FailureInsight (detects no_prior_success)
- ❌ No input validation on custom question (prompt injection risk)
- ❌ No result caching for analyze_run/diagnoseRegression
- ⚠️ Magic Job Generator overwrites form without preview/confirmation
- 🔍 Loading states could show timestamp of last analysis to indicate staleness

## Area 4: Investigate Canned Checks
*Analyzing scheduler/api/investigations.py for existing checks and gaps vs competitors*

### Findings
[To be populated]

## Area 5: Testing Coverage
*Reviewing test_ai.py and test_investigations.py for robustness*

### Findings
[To be populated]

## Area 6: Gaps vs State of the Art
*Identifying missing AI-assisted operability features in modern tools*

### Findings
[To be populated]

## Summary — Top 5 Priorities
[To be populated]
