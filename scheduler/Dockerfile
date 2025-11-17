FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY . /app/scheduler
WORKDIR /app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "8000"]
