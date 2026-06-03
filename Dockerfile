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

# Create data directory for SQLite DB, uploads and task stats
RUN mkdir -p /app/data/llm_logs /app/data/task_stats /app/data/uploads

# Copy entrypoint before switching to non-root user so chmod succeeds
COPY --chmod=755 entrypoint.sh /entrypoint.sh

# Non-root user for security
RUN useradd -r -u 1001 bpmtutor && chown -R bpmtutor:bpmtutor /app
USER bpmtutor

EXPOSE 5001

ENTRYPOINT ["/entrypoint.sh"]
