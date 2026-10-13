# ModelScope Studio Docker deployment image.
# The explicit COPY list intentionally excludes .env, .git, node_modules, and
# local SQLite files from the build context even when no .dockerignore exists.

FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
RUN npm ci --no-audit --no-fund
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FRONTEND_DIST_PATH=/app/frontend/dist \
    DATABASE_PATH=/mnt/workspace/field_navigator.sqlite3 \
    LIVE_REQUEST_BUDGET=30 \
    LIVE_MAX_CONCURRENCY=2

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /mnt/workspace \
    && chown -R app:app /mnt/workspace

COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

# Preserve the backend package layout so config.py resolves the application
# root at /app. Only application source is copied; no repository-wide COPY.
COPY --chown=app:app backend/app /app/backend/app
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

ENV PYTHONPATH=/app/backend

USER app
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
