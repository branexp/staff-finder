"""Jina AI search client with caching."""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import httpx  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception  # type: ignore

from .config import Settings  # type: ignore


def _extract_items(data) -> List[Dict]:
    """Extract result items from Jina response."""
    if isinstance(data, dict):
        for key in ("results", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    elif isinstance(data, list):
        return data
    return []


def _headers(cfg: Settings) -> Dict[str, str]:
    """Build headers for Jina API requests."""
    h = {
        "Authorization": f"Bearer {cfg.jina_api_key}",
        "Accept": "application/json",
        "User-Agent": "staff-finder/0.3"
    }
    if cfg.jina_no_cache:
        h["x-no-cache"] = "true"
    return h


def _cache_key(cache_dir: Path, q: str) -> Path:
    """Generate cache file path for a query."""
    return cache_dir / (hashlib.sha1(q.encode("utf-8")).hexdigest() + ".json")


def _retry_filter(exc: BaseException) -> bool:
    """Filter for retryable exceptions."""
    # retry only timeouts/connect errors and 429/5xx; do not retry on 4xx like 422
    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        r = exc.response
        if r is not None:
            return r.status_code == 429 or (500 <= r.status_code < 600)
    return False


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=8),
    retry=retry_if_exception(_retry_filter),
)
async def _jina_search(cfg: Settings, query: str, sites: Optional[List[str]] = None) -> List[Dict]:
    """Perform a Jina search request."""
    params: List[Tuple[str, str]] = [("q", query)]
    if sites:
        for s in sites:
            params.append(("site", s))
    timeout = httpx.Timeout(cfg.jina_request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{cfg.jina_base_url}/", params=params, headers=_headers(cfg))
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # 422 means "no results" — treat as empty without raising
            if e.response is not None and e.response.status_code == 422:
                return []
            raise
        data = resp.json()
    items = _extract_items(data)
    # normalize shape and omit non-dict junk
    out: List[Dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "title": (it.get("title") or ""),
            "url": (it.get("url") or ""),
            "content": (it.get("content") or it.get("description") or ""),
        })
    return out


async def search(cfg: Settings, query: str, sites: Optional[List[str]] = None) -> List[Dict]:
    """Cached async search if enabled."""
    if not cfg.enable_jina_cache:
        return await _jina_search(cfg, query, sites)

    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(cfg.cache_dir, query)
    if key.exists():
        try:
            cached = json.loads(key.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return cached
        except Exception:
            pass  # ignore cache read errors

    data = await _jina_search(cfg, query, sites)
    try:
        key.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return data
