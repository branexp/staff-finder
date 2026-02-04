from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from staff_finder.config import Settings
from staff_finder.jina_client import _retry_filter, search
from staff_finder.models import School
from staff_finder.openai_selector import pick_best_url_async
from staff_finder.resolver import resolve_for_school_async


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


@pytest.mark.asyncio
async def test_openai_pick_best_url_is_mockable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeResponses:
        async def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return type("Resp", (), {"output_text": json.dumps({"selected_url": "https://x.edu/staff"})})

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.responses = _FakeResponses()

    monkeypatch.setattr("staff_finder.openai_selector.AsyncOpenAI", _FakeClient)

    cfg = Settings(openai_api_key="sk_test", jina_api_key="jina_test")
    school = School(name="Test HS", district="", county="", city="", state="TX")
    raw = await pick_best_url_async(cfg, "sys", school, [{"url": "https://x.edu/staff"}])

    assert "https://x.edu/staff" in raw
    assert len(calls) == 1
    assert calls[0]["model"] == cfg.openai_model
    assert calls[0]["text"]["format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_resolver_end_to_end_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_jina_search(cfg: Settings, q: str, sites: list[str] | None = None) -> list[dict]:
        return [
            {
                "title": "Staff Directory",
                "url": "https://example.edu/staff",
                "content": "Directory",
            }
        ]

    async def fake_pick_best_url_async(
        cfg: Settings,
        system_instructions: str,
        school: School,
        candidates: list[dict],
    ) -> str:
        return json.dumps(
            {
                "selected_index": 0,
                "selected_url": "https://example.edu/staff",
                "confidence": "high",
                "reasoning": "fixture",
            }
        )

    monkeypatch.setattr("staff_finder.resolver.jina_search", fake_jina_search)
    monkeypatch.setattr("staff_finder.resolver.pick_best_url_async", fake_pick_best_url_async)

    cfg = Settings(openai_api_key="sk_test", jina_api_key="jina_test", enable_jina_cache=False)
    school = School(name="Test HS", district="", county="", city="", state="TX")

    result = await resolve_for_school_async(cfg, school)

    assert result.url == "https://example.edu/staff"
    assert result.confidence == "high"
    assert result.reasoning == "fixture"
