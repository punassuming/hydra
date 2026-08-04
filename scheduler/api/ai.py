import difflib
import json
import os
from enum import Enum
from typing import List, Literal, Optional

import google.generativeai as genai
import openai
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models.job_definition import JobCreate
from ..mongo_client import get_db

router = APIRouter(prefix="/ai", tags=["AI"])
MAX_PREDICTION_SAMPLE_SIZE = 200  # Cap query size to keep estimation requests fast.

# Shared log-truncation budget so every feature that hands log text to an LLM
# (analyze_run, diagnose_regression) truncates the same way.
STDERR_TAIL_CHARS = 6000
STDOUT_TAIL_CHARS = 2500

_DEFAULT_MODELS = {"gemini": "gemini-pro", "openai": "gpt-4o"}

class AIProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"

class AnalysisType(str, Enum):
    FAILURE = "failure"
    SUMMARY = "summary"
    ERRORS = "errors"
    RETRY = "retry"
    CUSTOM = "custom"

class GenerateRequest(BaseModel):
    prompt: str
    provider: AIProvider = AIProvider.GEMINI
    model: Optional[str] = None

class AnalyzeRequest(BaseModel):
    run_id: str
    stdout: str
    stderr: str
    exit_code: int
    analysis_type: AnalysisType = AnalysisType.FAILURE
    question: Optional[str] = None
    provider: AIProvider = AIProvider.GEMINI
    model: Optional[str] = None

class PredictDurationRequest(BaseModel):
    job_id: str
    sample_size: int = Field(default=20, ge=1, le=MAX_PREDICTION_SAMPLE_SIZE)
    domain: Optional[str] = None

class DiagnoseRegressionRequest(BaseModel):
    run_id: str
    provider: AIProvider = AIProvider.GEMINI
    model: Optional[str] = None

class DiagnoseRegressionResponse(BaseModel):
    likely_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: List[str]
    suggested_fix: str
    is_transient: bool
    compared_run_id: str
    compared_run_started_at: Optional[str] = None
    current_duration_seconds: Optional[float] = None
    baseline_p90_seconds: Optional[float] = None
    baseline_sample_size: int = 0

class _LLMDiagnosis(BaseModel):
    likely_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: List[str]
    suggested_fix: str
    is_transient: bool

SYSTEM_PROMPT_JOB = """
You are an expert job scheduler assistant. Convert the user's natural language request into a JSON
object matching the JobCreate schema.
Ensure valid JSON. Do not include markdown formatting (```json).

Only include fields that differ from defaults. A minimal job needs just name, executor, and schedule.

Minimal example:
{
  "name": "daily-backup",
  "executor": { "type": "shell", "script": "tar czf /backups/data.tar.gz /data" },
  "schedule": { "mode": "cron", "cron": "0 2 * * *", "enabled": true }
}

Available executor types and their recommended timeouts:
- shell (timeout: 60) / python (timeout: 300) / batch (timeout: 60, os: windows) / powershell (timeout: 120, os: windows)
- sql (timeout: 120, requires dialect + connection_uri or credential_ref) / http (timeout: 30, requires url)
- external (timeout: 60, requires command) / sensor (timeout: 3600, requires target + sensor_type)

Key fields (all optional except name + executor):
- retry_count: number of retries on failure (e.g. "retry 3 times" -> retry_count: 3)
- timeout: max execution seconds
- affinity.os: ["linux"] or ["windows"] (omit to match any)
- schedule.mode: "immediate" (default), "cron", or "interval"
- completion.exit_codes: [0] (default)

Do not include "domain" (derived from auth context).
"""

def _call_gemini(prompt: str, system: str = "", model_name: str = "gemini-pro") -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    full_prompt = f"{system}\n\nRequest: {prompt}" if system else prompt
    try:
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini Error: {str(e)}")

def _call_openai(prompt: str, system: str = "", model_name: str = "gpt-3.5-turbo") -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    
    client = openai.OpenAI(api_key=api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI Error: {str(e)}")

def _call_llm(provider: AIProvider, model: Optional[str], system: str, prompt: str) -> str:
    """Single dispatch point for every feature that needs an LLM call.

    Keeps the provider branching (and default-model lookup) in one place
    instead of duplicated per endpoint.
    """
    resolved_model = model or _DEFAULT_MODELS.get(provider.value)
    if provider == AIProvider.GEMINI:
        return _call_gemini(prompt, system, resolved_model)
    if provider == AIProvider.OPENAI:
        return _call_openai(prompt, system, resolved_model)
    raise HTTPException(status_code=400, detail="Invalid provider")

def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text

@router.post("/generate_job")
async def generate_job(req: GenerateRequest):
    text = _call_llm(req.provider, req.model, SYSTEM_PROMPT_JOB, req.prompt)

    try:
        cleaned = _clean_json(text)
        data = json.loads(cleaned)
        job = JobCreate(**data)
        return job.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse generated job: {str(e)}")

@router.post("/analyze_run")
async def analyze_run(req: AnalyzeRequest):
    stderr_tail = (req.stderr or "")[-STDERR_TAIL_CHARS:]
    stdout_tail = (req.stdout or "")[-STDOUT_TAIL_CHARS:]
    context = f"""
Run ID: {req.run_id}
Exit Code: {req.exit_code}
Stderr:
{stderr_tail}

Stdout:
{stdout_tail}
"""

    if req.analysis_type == AnalysisType.SUMMARY:
        prompt = f"""
You are analyzing scheduler job logs.
Summarize what happened in this run in 5-8 bullets:
- major phases
- key outputs
- probable outcome and confidence
- any suspicious signals
{context}
"""
    elif req.analysis_type == AnalysisType.ERRORS:
        prompt = f"""
You are analyzing scheduler job logs.
Extract and normalize concrete error signals:
- error signatures (deduplicated)
- likely root cause category
- the first relevant failing line
- suggested regex patterns to detect this issue next time
Respond with concise sections and include exact snippets only when needed.
{context}
"""
    elif req.analysis_type == AnalysisType.RETRY:
        prompt = f"""
You are analyzing scheduler job logs.
Recommend retry and timeout tuning for this job:
- should retries increase/decrease and why
- suggested timeout value strategy
- whether failure appears transient vs deterministic
- guardrails to avoid retry storms
{context}
"""
    elif req.analysis_type == AnalysisType.CUSTOM:
        question = (req.question or "").strip() or "Analyze this run and provide practical debugging guidance."
        prompt = f"""
You are analyzing scheduler job logs.
Answer the user question using only evidence from these logs.
Question: {question}
{context}
"""
    else:
        prompt = f"""
Analyze the following job failure and provide actionable remediation steps.
Exit Code: {req.exit_code}
Stderr: {stderr_tail}
Stdout: {stdout_tail}

Provide a concise summary of the error and 1-3 specific steps to fix it.
"""

    text = _call_llm(req.provider, req.model, "", prompt)
    return {"analysis": text}


def _percentile(sorted_values, p: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = (len(sorted_values) - 1) * p
    lower = int(idx)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = idx - lower
    return float(sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction)


def duration_percentiles(
    db, job_id: str, domain_filter: Optional[str], sample_size: int, exclude_run_id: Optional[str] = None
) -> Optional[dict]:
    """Historical duration stats for a job — shared by predict_duration and diagnose_regression."""
    query = {
        "job_id": job_id,
        "status": {"$in": ["success", "failed"]},
        "duration": {"$gte": 0},
    }
    if domain_filter:
        query["domain"] = domain_filter
    if exclude_run_id:
        query["_id"] = {"$ne": exclude_run_id}

    runs = list(db.job_runs.find(query).sort("start_ts", -1).limit(sample_size))
    durations = sorted(
        float(run["duration"])
        for run in runs
        if isinstance(run.get("duration"), (int, float)) and run["duration"] >= 0
    )
    if not durations:
        return None
    return {
        "sample_size": len(durations),
        "median_seconds": _percentile(durations, 0.5),
        "mean_seconds": sum(durations) / len(durations),
        "p90_seconds": _percentile(durations, 0.9),
    }


@router.post("/predict_duration")
async def predict_duration(req: PredictDurationRequest, request: Request):
    db = get_db()
    sample_size = min(req.sample_size, MAX_PREDICTION_SAMPLE_SIZE)
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)

    domain_filter = None
    if not is_admin:
        domain_filter = domain
    elif req.domain:
        domain_filter = req.domain

    stats = duration_percentiles(db, req.job_id, domain_filter, sample_size)
    if not stats:
        return {"job_id": req.job_id, "sample_size": 0, "estimated_duration_seconds": None, "p90_duration_seconds": None}

    return {
        "job_id": req.job_id,
        "sample_size": stats["sample_size"],
        "estimated_duration_seconds": stats["median_seconds"],  # Median is more stable for skewed runtimes.
        "mean_duration_seconds": stats["mean_seconds"],
        "p90_duration_seconds": stats["p90_seconds"],
    }


def _unified_log_diff(baseline_log: str, current_log: str, max_lines: int = 200) -> str:
    diff = list(
        difflib.unified_diff(
            baseline_log.splitlines(),
            current_log.splitlines(),
            fromfile="last_success",
            tofile="this_run",
            lineterm="",
        )
    )
    if not diff:
        return "(no textual difference between this run's output and the last successful run's output)"
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... ({len(diff) - max_lines} more diff lines truncated) ..."]
    return "\n".join(diff)


SYSTEM_PROMPT_DIAGNOSE_REGRESSION = """
You are an expert SRE assistant diagnosing why a scheduled job run failed. You are given a
diff between this run's output and the most recent successful run's output, plus duration
data, as your primary evidence — ground your answer in that evidence rather than guessing.

Respond with ONLY a JSON object (no markdown fences) matching this schema:
{
  "likely_cause": "<one sentence>",
  "confidence": "low" | "medium" | "high",
  "evidence": ["<short evidence bullet>", "..."],
  "suggested_fix": "<concrete next step(s)>",
  "is_transient": true | false
}

If the diff shows no meaningful change and duration is in the normal range, say so explicitly
and prefer a transient explanation (e.g. network blip, resource contention) over inventing a
code-level cause you cannot support from the evidence.
"""


@router.post("/diagnose_regression")
async def diagnose_regression(req: DiagnoseRegressionRequest, request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)

    current = db.job_runs.find_one({"_id": req.run_id})
    if not current:
        raise HTTPException(status_code=404, detail="run not found")
    run_domain = current.get("domain", "prod")
    if not is_admin and run_domain != domain:
        raise HTTPException(status_code=403, detail="forbidden")

    job_id = current.get("job_id")
    baseline_query = {"job_id": job_id, "status": "success", "_id": {"$ne": req.run_id}}
    current_start = current.get("start_ts")
    if current_start:
        baseline_query["start_ts"] = {"$lt": current_start}
    baseline = next(iter(db.job_runs.find(baseline_query).sort("start_ts", -1).limit(1)), None)
    if not baseline:
        raise HTTPException(
            status_code=422,
            detail="no_prior_success: no successful run of this job exists yet to compare against",
        )

    job_doc = db.job_definitions.find_one({"_id": job_id}, {"name": 1}) or {}
    job_name = job_doc.get("name", job_id)

    stats = duration_percentiles(db, job_id, run_domain, MAX_PREDICTION_SAMPLE_SIZE, exclude_run_id=req.run_id)
    current_duration = current.get("duration")
    if stats and isinstance(current_duration, (int, float)):
        duration_line = (
            f"Duration comparison: this run took {current_duration:.1f}s vs a historical "
            f"p90 of {stats['p90_seconds']:.1f}s (median {stats['median_seconds']:.1f}s, "
            f"n={stats['sample_size']})."
        )
        if stats["p90_seconds"] and current_duration >= 2 * stats["p90_seconds"]:
            duration_line += " This run took notably longer than usual."
    else:
        duration_line = "No historical duration baseline is available yet for this job."

    current_log = (
        f"STDOUT:\n{(current.get('stdout') or '')[-STDOUT_TAIL_CHARS:]}\n\n"
        f"STDERR:\n{(current.get('stderr') or '')[-STDERR_TAIL_CHARS:]}"
    )
    baseline_log = (
        f"STDOUT:\n{(baseline.get('stdout') or '')[-STDOUT_TAIL_CHARS:]}\n\n"
        f"STDERR:\n{(baseline.get('stderr') or '')[-STDERR_TAIL_CHARS:]}"
    )
    diff_text = _unified_log_diff(baseline_log, current_log)

    baseline_started = baseline.get("start_ts")
    prompt = f"""
Job: {job_name} ({job_id})
This run: id={req.run_id} status={current.get('status')} exit_code={current.get('returncode')}
Compared against last success: id={baseline.get('_id')} started at {baseline_started}
{duration_line}

Unified diff of this run's output against the last successful run's output:
{diff_text}
"""

    text = _call_llm(req.provider, req.model, SYSTEM_PROMPT_DIAGNOSE_REGRESSION, prompt)
    try:
        parsed = _LLMDiagnosis.model_validate_json(_clean_json(text))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse diagnosis: {str(e)}")

    return DiagnoseRegressionResponse(
        likely_cause=parsed.likely_cause,
        confidence=parsed.confidence,
        evidence=parsed.evidence,
        suggested_fix=parsed.suggested_fix,
        is_transient=parsed.is_transient,
        compared_run_id=str(baseline.get("_id")),
        compared_run_started_at=baseline_started.isoformat() if hasattr(baseline_started, "isoformat") else baseline_started,
        current_duration_seconds=float(current_duration) if isinstance(current_duration, (int, float)) else None,
        baseline_p90_seconds=stats["p90_seconds"] if stats else None,
        baseline_sample_size=stats["sample_size"] if stats else 0,
    )
