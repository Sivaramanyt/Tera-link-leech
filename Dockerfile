# Dockerfile
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Health endpoint (scripts/health.py) runs on 0.0.0.0:8080
ENV HEALTH_HOST=0.0.0.0
ENV HEALTH_PORT=8080
EXPOSE 8080

# Use tini as init for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start health server then bot
CMD ["bash", "start.sh"]
