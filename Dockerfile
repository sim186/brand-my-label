FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY brand_my_label/ brand_my_label/
RUN pip install --no-cache-dir ".[server]"
COPY server/ server/

RUN useradd --create-home --uid 10001 app
USER app

# Cloud Run injects $PORT
CMD ["sh", "-c", "exec uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
