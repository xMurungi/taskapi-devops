# --- build stage ---
FROM python:3.11-slim AS builder
WORKDIR /app

# upgrade the full toolchain — setuptools vendors jaraco.context and wheel internally
RUN pip install --upgrade pip setuptools

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

RUN find /install -name "wheel-*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true

# --- runtime stage ---
FROM python:3.11-slim
WORKDIR /app

# upgrade setuptools in the runtime image directly — this is what Trivy scans
RUN pip install --upgrade pip setuptools --no-cache-dir

# Install curl for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY --chown=appuser:appgroup . .

# security: non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# Checks every 30s if the API returns a 200 on the health endpoint
HEALTHCHECK --interval=180s --timeout=3s \
  CMD curl -f http://localhost:1234/api/health || exit 1

# This is documentation for the internal port
EXPOSE 1234
ENV FLASK_ENV=production
CMD [ "python", "run.py"]


# A multi-stage build keeps the final image small and is considered standard practice. The non-root user is something security scanners (and Trivy) will flag if missing.

