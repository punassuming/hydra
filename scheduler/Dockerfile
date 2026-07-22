FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY . /app/scheduler
WORKDIR /app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# /health bypasses auth (see scheduler/utils/auth.py::_is_allowed_path) and
# touches Mongo/Redis, so a failing check means the API is up but can't
# actually serve requests — not just "the process started".
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "8000"]
