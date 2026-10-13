"""Static and optional local HTTP checks for the ModelScope Docker image.

This helper intentionally uses only the Python standard library. It never reads
the repository's .env file and never calls ModelScope APIs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def _active_docker_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def static_checks() -> list[str]:
    errors: list[str] = []
    dockerfile_path = ROOT / "Dockerfile"
    deploy_path = ROOT / "ms_deploy.json"

    if not dockerfile_path.is_file():
        errors.append("missing root Dockerfile")
        return errors
    if not deploy_path.is_file():
        errors.append("missing root ms_deploy.json")
        return errors

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    active_lines = _active_docker_lines(dockerfile)
    try:
        deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid ms_deploy.json: {exc}")
        return errors

    if deploy.get("sdk_type") != "docker":
        errors.append('ms_deploy.json sdk_type must be "docker"')
    if deploy.get("port") != 7860:
        errors.append("ms_deploy.json port must be 7860")
    if not isinstance(deploy.get("resource_configuration"), str) or not deploy["resource_configuration"]:
        errors.append("ms_deploy.json resource_configuration is missing")

    required_fragments = (
        "FROM node:22",
        "FROM python:3.12-slim",
        "EXPOSE 7860",
        "FRONTEND_DIST_PATH=/app/frontend/dist",
        "DATABASE_PATH=/mnt/workspace/field_navigator.sqlite3",
        "LIVE_REQUEST_BUDGET=30",
        "LIVE_MAX_CONCURRENCY=2",
        '"--host", "0.0.0.0"',
        '"--port", "7860"',
        '"--workers", "1"',
        "USER app",
    )
    for fragment in required_fragments:
        if fragment not in dockerfile:
            errors.append(f"Dockerfile missing required setting: {fragment}")

    if any(re.match(r"^(?:COPY|ADD)\s+(?:--[^\s]+\s+)*\.\s", line, re.IGNORECASE) for line in active_lines):
        errors.append("Dockerfile must not copy the repository root")
    if any(line.startswith("COPY frontend/ ./") or line.startswith("COPY backend/ ./") for line in active_lines):
        errors.append("Dockerfile must use a source whitelist instead of broad application COPY")

    return errors


def http_check(base_url: str, timeout: float) -> list[str]:
    errors: list[str] = []
    base_url = base_url.rstrip("/")
    for path in ("/api/health", "/"):
        request = Request(f"{base_url}{path}", headers={"Accept": "application/json" if path.startswith("/api/") else "text/html"})
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(1024 if path.startswith("/api/") else 16384).decode("utf-8", errors="replace")
                if response.status != 200:
                    errors.append(f"{path} returned HTTP {response.status}")
                if path == "/api/health":
                    try:
                        if json.loads(body).get("status") != "ok":
                            errors.append("/api/health did not report status=ok")
                    except json.JSONDecodeError:
                        errors.append("/api/health did not return JSON")
                elif "<div id=\"root\">" not in body and "Field Navigator" not in body:
                    errors.append("/ did not return the Field Navigator shell")
        except HTTPError as exc:
            errors.append(f"{path} returned HTTP {exc.code}")
        except URLError as exc:
            errors.append(f"{path} is unreachable: {exc.reason}")
        except TimeoutError:
            errors.append(f"{path} timed out")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Field Navigator ModelScope Docker setup")
    parser.add_argument("--url", help="optional running image URL, for example http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    errors = static_checks()
    if args.url:
        errors.extend(http_check(args.url, args.timeout))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: ModelScope Docker static checks")
    if args.url:
        print(f"PASS: local HTTP checks at {args.url.rstrip('/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
