FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.13
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY scheduler /app/scheduler

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# /health bypasses auth (see scheduler/utils/auth.py::_is_allowed_path) and
# touches Mongo/Redis, so a failing check means the API is up but can't
# actually serve requests — not just "the process started".
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "8000"]
