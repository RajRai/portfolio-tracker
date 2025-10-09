# =========================
# 1. Frontend build stage
# =========================
FROM node:20-alpine AS client-build
WORKDIR /app/client

COPY client/package*.json ./
RUN npm ci
COPY client/ .
RUN npm run build

# =========================
# 2. Backend runtime stage
# =========================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend + built client
COPY . .
COPY --from=client-build /app/client/dist ./client/dist

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV FLASK_PORT=8000
EXPOSE 8000

# Start both server and watcher
CMD ["python", "start.py"]
