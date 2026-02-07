"""URL utilities for sanitization and extraction."""

import re
from urllib.parse import urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s\"'>)]+", re.IGNORECASE)


def sanitize_url(url: str | None) -> str | None:
    """Sanitize and normalize a URL.

    Args:
        url: The URL to sanitize

    Returns:
        Normalized URL or None if invalid
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        parts = urlsplit(url)
        # drop fragments, normalize scheme/host
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except Exception:
        return None
