# Máy chủ CodeChalk (FastAPI). Bài nộp được chấm trong container riêng (judge/Dockerfile).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Lệnh docker để mở container chấm bài qua /var/run/docker.sock
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements-postgres.txt

COPY app ./app
COPY judge ./judge
COPY web ./web
COPY scripts/load_challenges.py scripts/sqlite_to_postgres.py ./scripts/
COPY data/challenges.json ./data/challenges.json

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
