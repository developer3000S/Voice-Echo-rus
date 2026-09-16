"""
Centralized proxy configuration for Voice Echo.

Routes all HTTP/HTTPS traffic through a configured proxy when present.
Settings are persisted in ``config/app_settings.json`` under ``proxy_url``
and can also be overridden with the ``VOICE_ECHO_PROXY`` environment variable.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx

SETTINGS_PATH = Path(__file__).resolve().parent / "config" / "app_settings.json"

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_proxy_url: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    os.makedirs(SETTINGS_PATH.parent, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _ensure_env_proxies() -> None:
    """Set ``HTTP_PROXY``/``HTTPS_PROXY`` in the process environment.

    ``requests`` and Playwright (Chromium/Chrome) honor these variables.
    """
    proxy = get_proxy_url()
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    else:
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_proxy_enforced: bool = False

def get_proxy_url() -> str:
    """Return the current proxy URL (empty string when disabled)."""
    global _proxy_url
    if _proxy_url:
        return _proxy_url
    _proxy_url = (
        os.environ.get("VOICE_ECHO_PROXY")
        or _load_settings().get("proxy_url", "")
        or ""
    )
    return _proxy_url


def set_system_proxy(url: str) -> None:
    """Set system proxy for all applications using environment variables."""
    url = url.strip()
    if url:
        # Set system environment variables
        os.environ["HTTP_PROXY"] = url
        os.environ["HTTPS_PROXY"] = url
        # For systems that also use these
        os.environ["http_proxy"] = url
        os.environ["https_proxy"] = url
    else:
        # Clear system proxy
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)


def set_proxy_url(url: str) -> None:
    """Set the proxy URL, persist it, and apply it to the current process."""
    global _proxy_url
    _proxy_url = url.strip()
    data = _load_settings()
    data["proxy_url"] = _proxy_url
    _save_settings(data)
    _ensure_env_proxies()
    set_system_proxy(_proxy_url)


def set_proxy_enforced(enforced: bool) -> None:
    """Enable/disable proxy enforcement mode. When enforced, network operations fail if proxy is not configured."""
    global _proxy_enforced
    _proxy_enforced = bool(enforced)
    data = _load_settings()
    data["proxy_enforced"] = _proxy_enforced
    _save_settings(data)


def is_proxy_enforced() -> bool:
    """Check if proxy enforcement mode is enabled."""
    return _proxy_enforced


def get_httpx_client() -> httpx.Client:
    """Return a cached ``httpx.Client`` configured with the current proxy."""
    proxy = get_proxy_url()
    if _proxy_enforced and not proxy:
        raise RuntimeError("Proxy enforcement is enabled but no proxy URL is configured")
    kwargs: dict = {"timeout": httpx.Timeout(120.0, connect=30.0)}
    if proxy:
        kwargs["proxies"] = {"http://": proxy, "https://": proxy}
    if not hasattr(get_httpx_client, "_client") or get_httpx_client._client is None:
        get_httpx_client._client = httpx.Client(**kwargs)  # type: ignore[attr-defined]
    return get_httpx_client._client  # type: ignore[attr-defined]


def get_httpx_async_client() -> httpx.AsyncClient:
    """Return a cached ``httpx.AsyncClient`` configured with the current proxy."""
    proxy = get_proxy_url()
    if _proxy_enforced and not proxy:
        raise RuntimeError("Proxy enforcement is enabled but no proxy URL is configured")
    kwargs: dict = {"timeout": httpx.Timeout(120.0, connect=30.0)}
    if proxy:
        kwargs["proxies"] = {"http://": proxy, "https://": proxy}
    if not hasattr(get_httpx_async_client, "_client") or get_httpx_async_client._client is None:
        get_httpx_async_client._client = httpx.AsyncClient(**kwargs)  # type: ignore[attr-defined]
    return get_httpx_async_client._client  # type: ignore[attr-defined]


# Initialize env on import
_ensure_env_proxies()
