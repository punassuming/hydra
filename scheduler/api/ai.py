import os
import json
from enum import Enum
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
import openai
from ..models.job_definition import JobCreate

router = APIRouter(prefix="/ai", tags=["AI"])

class AIProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"

class GenerateRequest(BaseModel):
    prompt: str
    provider: AIProvider = AIProvider.GEMINI
    model: Optional[str] = None

class AnalyzeRequest(BaseModel):
    run_id: str
    stdout: str
    stderr: str
    exit_code: int
    provider: AIProvider = AIProvider.GEMINI
    model: Optional[str] = None

SYSTEM_PROMPT_JOB = """
You are an expert job scheduler assistant. Convert the user's natural language request into a JSON object matching the following structure (JobCreate).
Ensure valid JSON. Do not include markdown formatting (```json).

Structure:
{
  "name": "string",
  "domain": "prod",
  "affinity": { "os": ["linux"], "tags": [], "allowed_users": [] },
  "executor": { "type": "shell", "script": "echo hello" }, // or python/batch/external
  "schedule": { "mode": "immediate", "cron": null, "interval_seconds": null, "enabled": true },
  "completion": { "exit_codes": [0] }
}

Defaults:
- executor type: shell
- schedule mode: immediate (unless frequency mentioned)
- affinity os: linux
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
    
    prompt = f"""
    Analyze the following job failure and provide actionable remediation steps.
    Exit Code: {req.exit_code}
    Stderr: {req.stderr[-4000:]}
    Stdout: {req.stdout[-1000:]}
    
    Provide a concise summary of the error and 1-3 specific steps to fix it.
    """
    
    if provider == AIProvider.GEMINI:
        text = _call_gemini(prompt, "", model)
    elif provider == AIProvider.OPENAI:
        text = _call_openai(prompt, "", model)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")
        
    return {"analysis": text}