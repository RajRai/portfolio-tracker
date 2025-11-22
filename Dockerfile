# =========================
# 1. Frontend build stage
# =========================
FROM node:20-alpine AS client-build
WORKDIR /app/client

# Install deps first (cached unless package*.json changes)
COPY client/package*.json ./
RUN npm ci

# Copy app source (invalidates only build step)
COPY client/ .
RUN npm run build


# =========================
# 2. Backend runtime stage
# =========================
FROM python:3.11-slim

WORKDIR /app

# --- Install OS-level deps (rarely changes) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# --- Install Python deps (cached unless requirements.txt changes) ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# --- Copy backend AFTER deps (changes often) ---
COPY src/ ./src

# --- Copy client output AFTER deps (changes often) ---
COPY --from=client-build /app/client/dist ./client/dist

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV FLASK_PORT=8000

EXPOSE 8000
CMD ["python", "src/start.py"]
