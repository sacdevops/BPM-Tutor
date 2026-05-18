# BPM-Tutor — production Dockerfile
FROM python:3.11-slim

# System dependencies for lxml and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Create data directory for the SQLite database and uploads
RUN mkdir -p /app/data/llm_logs /app/data/task_stats /app/data/uploads

# Non-root user for security
RUN useradd -r -u 1001 bpmtutor && chown -R bpmtutor:bpmtutor /app
USER bpmtutor

EXPOSE 8080

# Gunicorn + gevent (Flask-SocketIO async worker)
# Railway injects $PORT at runtime; fall back to 8080 locally
CMD ["sh", "-c", "gunicorn --worker-class gevent --workers 1 --bind 0.0.0.0:${PORT:-8080} --timeout 120 --access-logfile - --error-logfile - main:app"]
