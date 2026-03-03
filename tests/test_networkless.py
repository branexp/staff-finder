from __future__ import annotations

import httpx
import pytest
import respx

from staff_finder.config import Settings
from staff_finder.jina_client import _retry_filter, search


@pytest.mark.asyncio
async def test_jina_search_422_returns_empty() -> None:
    cfg = Settings(
        jina_api_key="jina_test",
        openai_api_key="sk_test",
        enable_jina_cache=False,
    )

    with respx.mock(assert_all_called=True) as router:
        router.get("https://s.jina.ai/").mock(
            return_value=httpx.Response(422, json={"detail": "no"})
        )
        out = await search(cfg, "example query")

    assert out == []


def test_jina_retry_filter() -> None:
    assert _retry_filter(httpx.ReadTimeout("boom")) is True
    assert _retry_filter(httpx.ConnectError("boom")) is True

    # 429 should be retryable
    resp_429 = httpx.Response(429, request=httpx.Request("GET", "https://s.jina.ai/"))
    err_429 = httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429)
    assert _retry_filter(err_429) is True

    # 422 should NOT be retryable (and is treated as empty result upstream)
    resp_422 = httpx.Response(422, request=httpx.Request("GET", "https://s.jina.ai/"))
    err_422 = httpx.HTTPStatusError("422", request=resp_422.request, response=resp_422)
    assert _retry_filter(err_422) is False
