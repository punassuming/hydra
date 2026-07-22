import json
import os
from enum import Enum
from typing import Optional

import google.generativeai as genai
import openai
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models.job_definition import JobCreate
from ..mongo_client import get_db

router = APIRouter(prefix="/ai", tags=["AI"])
MAX_PREDICTION_SAMPLE_SIZE = 200  # Cap query size to keep estimation requests fast.

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
    provider = req.provider
    model = req.model or ("gemini-pro" if provider == AIProvider.GEMINI else "gpt-4o")
    
    if provider == AIProvider.GEMINI:
        text = _call_gemini(req.prompt, SYSTEM_PROMPT_JOB, model)
    elif provider == AIProvider.OPENAI:
        text = _call_openai(req.prompt, SYSTEM_PROMPT_JOB, model)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")
        
    try:
        cleaned = _clean_json(text)
        data = json.loads(cleaned)
        job = JobCreate(**data)
        return job.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse generated job: {str(e)}")

@router.post("/analyze_run")
async def analyze_run(req: AnalyzeRequest):
    provider = req.provider
    model = req.model or ("gemini-pro" if provider == AIProvider.GEMINI else "gpt-4o")

    stderr_tail = (req.stderr or "")[-6000:]
    stdout_tail = (req.stdout or "")[-2500:]
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
    
    if provider == AIProvider.GEMINI:
        text = _call_gemini(prompt, "", model)
    elif provider == AIProvider.OPENAI:
        text = _call_openai(prompt, "", model)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")
        
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


@router.post("/predict_duration")
async def predict_duration(req: PredictDurationRequest, request: Request):
    db = get_db()
    sample_size = min(req.sample_size, MAX_PREDICTION_SAMPLE_SIZE)
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)

    query = {
        "job_id": req.job_id,
        "status": {"$in": ["success", "failed"]},
        "duration": {"$gte": 0},
    }
    if not is_admin:
        query["domain"] = domain
    elif req.domain:
        query["domain"] = req.domain

    runs = list(db.job_runs.find(query).sort("start_ts", -1).limit(sample_size))
    durations = []
    for run in runs:
        duration = run.get("duration")
        if isinstance(duration, (int, float)) and duration >= 0:
            durations.append(float(duration))
    durations.sort()
    if not durations:
        return {"job_id": req.job_id, "sample_size": 0, "estimated_duration_seconds": None, "p90_duration_seconds": None}

    mean_seconds = sum(durations) / len(durations)
    median_seconds = _percentile(durations, 0.5)
    p90_seconds = _percentile(durations, 0.9)
    return {
        "job_id": req.job_id,
        "sample_size": len(durations),
        "estimated_duration_seconds": median_seconds,  # Median estimate is more stable for skewed runtimes.
        "mean_duration_seconds": mean_seconds,
        "p90_duration_seconds": p90_seconds,
    }
