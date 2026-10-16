# ModelScope Studio bootstrap image.
#
# This upload package is intentionally flat.  The application source is fetched
# at a fixed public commit during the build, so the package itself only needs
# to contain this Dockerfile and the Studio metadata/documentation files.

FROM node:22-bookworm-slim AS source-and-frontend-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Keep the source pin literal: this image must not silently follow main.
RUN git init /src \
    && git -C /src remote add origin https://github.com/Iterating0/field-navigator.git \
    && git -C /src fetch --depth 1 origin fe4fd4f6c22f72133a25dcb97251af4cb1ab4e5c \
    && git -C /src checkout --detach FETCH_HEAD

WORKDIR /src/frontend
RUN npm ci --no-audit --no-fund \
    && npm run build

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

COPY --from=source-and-frontend-build /src/backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

COPY --from=source-and-frontend-build --chown=app:app /src/backend/app /app/backend/app
COPY --from=source-and-frontend-build --chown=app:app /src/frontend/dist /app/frontend/dist

ENV PYTHONPATH=/app/backend

USER app
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
