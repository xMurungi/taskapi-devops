# --- build stage ---
FROM python:3.11-slim AS builder
WORKDIR /app

# upgrade pip toolchain first to get patched versions
RUN pip install --upgrade pip wheel jaraco.context

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime stage ---
FROM python:3.11-slim
WORKDIR /app
# Install curl for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY . .

# security: non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
COPY --chown=appuser:appgroup . .
USER appuser

# Checks every 30s if the API returns a 200 on the health endpoint
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:1234/api/health || exit 1

# This is documentation for the internal port
EXPOSE 1234
ENV FLASK_ENV=production
CMD [ "python", "run.py"]


# A multi-stage build keeps the final image small and is considered standard practice. The non-root user is something security scanners (and Trivy) will flag if missing.

