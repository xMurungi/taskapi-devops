FROM python:3.11-alpine AS builder
WORKDIR /app
RUN pip install --upgrade pip setuptools
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-alpine
WORKDIR /app
RUN apk add --no-cache curl
COPY --from=builder /install /usr/local
COPY --chown=appuser:appgroup . .
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE ${{ values.port }}
ENV FLASK_ENV=production
CMD ["python", "run.py"]
