from __future__ import annotations

import json
import math
import os
import threading
from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

import requests

POSTHOG_PROXY_PATH = "/api/posthog"
POSTHOG_CAPTURE_PATH = "/i/v0/e/"

_FORWARDED_REQUEST_HEADERS = (
    "Accept",
    "Content-Encoding",
    "Content-Type",
    "User-Agent",
)
_FORWARDED_RESPONSE_HEADERS = (
    "Cache-Control",
    "Content-Type",
    "ETag",
    "Last-Modified",
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _env_flag(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def posthog_host() -> str:
    return _env("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")


def posthog_ui_host() -> str | None:
    explicit = _env("POSTHOG_UI_HOST")
    if explicit:
        return explicit.rstrip("/")

    parsed = urlparse(posthog_host())
    if parsed.scheme and parsed.netloc.endswith(".i.posthog.com"):
        return f"{parsed.scheme}://{parsed.netloc.replace('.i.posthog.com', '.posthog.com')}"
    return None


def posthog_project_token() -> str:
    return _env("POSTHOG_PROJECT_TOKEN")


def posthog_enabled() -> bool:
    return bool(posthog_project_token())


def build_posthog_public_config() -> dict[str, object]:
    enabled = posthog_enabled()
    return {
        "enabled": enabled,
        # Keep the PostHog proxy same-origin so HTTPS deployments behind a
        # reverse proxy never emit an http:// apiHost that the browser blocks
        # as mixed content.
        "apiHost": POSTHOG_PROXY_PATH,
        "projectToken": posthog_project_token() if enabled else "",
        "uiHost": posthog_ui_host(),
        "debug": _env_flag("POSTHOG_DEBUG") or _env("FLASK_ENV") == "development",
        "respectDnt": _env_flag("POSTHOG_RESPECT_DNT"),
    }


def forward_posthog_request(
    path: str,
    *,
    method: str,
    query_params: Sequence[tuple[str, str]],
    body: bytes | None,
    headers: Mapping[str, str],
) -> tuple[bytes, int, dict[str, str]]:
    if not posthog_enabled():
        raise RuntimeError("PostHog is not configured")

    upstream_url = f"{posthog_host()}/{path.lstrip('/')}"
    forwarded_headers = {
        key: value
        for key, value in headers.items()
        if key in _FORWARDED_REQUEST_HEADERS and value
    }
    response = requests.request(
        method=method.upper(),
        url=upstream_url,
        params=list(query_params),
        data=body or None,
        headers=forwarded_headers,
        allow_redirects=False,
        timeout=(5, 30),
    )
    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key in _FORWARDED_RESPONSE_HEADERS and value
    }
    return response.content, response.status_code, response_headers


def _clean_property_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed[:200] if trimmed else None
    return None


def build_backend_capture_payload(
    headers: Mapping[str, str],
    *,
    route: str,
    success: bool,
    status_code: int,
    duration_ms: int,
    extra_properties: Mapping[str, object] | None = None,
    event_name: str = "backend_api_request",
) -> dict[str, object] | None:
    token = posthog_project_token()
    distinct_id = str(headers.get("X-PostHog-Distinct-Id") or "").strip()
    if not token or not distinct_id:
        return None

    session_id = str(headers.get("X-PostHog-Session-Id") or "").strip() or None
    properties: dict[str, object] = {
        "$process_person_profile": False,
        "source": "backend",
        "route": route,
        "success": success,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }
    if session_id:
        properties["$session_id"] = session_id

    for key, value in (extra_properties or {}).items():
        cleaned = _clean_property_value(value)
        if cleaned is not None:
            properties[key] = cleaned

    return {
        "api_key": token,
        "event": event_name,
        "distinct_id": distinct_id,
        "properties": properties,
    }


def _post_capture_payload(payload: Mapping[str, object]) -> None:
    try:
        requests.post(
            f"{posthog_host()}{POSTHOG_CAPTURE_PATH}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=5,
        )
    except requests.RequestException:
        # Analytics should never affect request handling.
        return


def capture_backend_event_async(payload: Mapping[str, object] | None) -> None:
    if not payload:
        return
    threading.Thread(target=_post_capture_payload, args=(payload,), daemon=True).start()
