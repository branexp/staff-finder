"""Shared utilities for batch tasks."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import pandas as pd  # type: ignore


def require_column(df: pd.DataFrame, *aliases: str) -> str:
    """Return the actual column name matching one of the aliases (case-insensitive)."""
    lower = {c.lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    raise ValueError(
        f"Missing required column. Expected one of: {', '.join(aliases)}. "
        f"Found: {', '.join(df.columns)}"
    )


def strip_json_fence(value: str) -> str:
    """Strip markdown code fence from a JSON response string."""
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def normalize_domain(url: str | None) -> str | None:
    """Normalize a URL to a bare domain (lowercase, no www, no scheme)."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def parse_json_response(raw: str | None) -> dict[str, Any] | None:
    """Parse a JSON response, stripping markdown fences if present."""
    if not raw:
        return None
    text = strip_json_fence(raw)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def validate_nces_id(value: str | None) -> str | None:
    """Validate and return a 7-digit NCES District ID, or None if invalid."""
    if not value:
        return None
    candidate = str(value).strip()
    if not re.match(r"^\d{7}$", candidate):
        return None
    return candidate
