FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user. /app/data holds the database, screenshots and the admin key.
RUN useradd --create-home --uid 10001 himaya \
    && mkdir -p /app/data \
    && chown -R himaya:himaya /app/data
USER himaya

EXPOSE 8000

# No curl needed: ask the hub's own /health endpoint with Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)" || exit 1

# Render assigns PORT dynamically; local Docker uses 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
