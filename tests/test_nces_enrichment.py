"""Tests for the NCES district ID enrichment pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from staff_finder.nces_enrichment import (
    _format_search_results,
    _jina_fetch,
    build_fallback_query,
    build_primary_query,
    parse_nces_response,
    run_enrichment,
)

# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------


def test_build_primary_query():
    q = build_primary_query("Acme Unified School District", "CA")
    assert '"Acme Unified School District"' in q
    assert '"CA"' in q
    assert '"NCES District ID"' in q


def test_build_fallback_query():
    q = build_fallback_query("Acme Unified School District", "CA")
    assert '"Acme Unified School District"' in q
    assert '"CA"' in q
    assert "site:nces.ed.gov" in q
    assert "site:publicschoolreview.com" in q


# ---------------------------------------------------------------------------
# Search result formatter
# ---------------------------------------------------------------------------


def test_format_search_results_limits_to_two():
    results = [
        {"title": "Title 1", "url": "https://a.com", "content": "Content 1"},
        {"title": "Title 2", "url": "https://b.com", "content": "Content 2"},
        {"title": "Title 3", "url": "https://c.com", "content": "Content 3"},
    ]
    formatted = _format_search_results(results, max_results=2)
    assert "[1]" in formatted
    assert "[2]" in formatted
    assert "[3]" not in formatted


def test_format_search_results_empty():
    assert _format_search_results([]) == ""


def test_format_search_results_single():
    results = [{"title": "NCES Page", "url": "https://nces.ed.gov/x", "content": "ID: 1234567"}]
    formatted = _format_search_results(results)
    assert "NCES Page" in formatted
    assert "https://nces.ed.gov/x" in formatted
    assert "ID: 1234567" in formatted


def test_format_search_results_truncates_content():
    long_content = "x" * 3000
    results = [{"title": "T", "url": "https://x.com", "content": long_content}]
    formatted = _format_search_results(results, max_content_chars=100)
    # Truncated content ends with "..."
    assert formatted.endswith("...")
    # Content portion must not exceed 103 chars (100 + "...")
    content_part = formatted.split("content: ", 1)[1]
    assert len(content_part) == 103


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------


def test_parse_nces_response_valid_id():
    raw = '{"nces_district_id":"1234567"}'
    assert parse_nces_response(raw) == "1234567"


def test_parse_nces_response_null():
    raw = '{"nces_district_id":null}'
    assert parse_nces_response(raw) is None


def test_parse_nces_response_empty_string():
    assert parse_nces_response("") is None


def test_parse_nces_response_none():
    assert parse_nces_response(None) is None


def test_parse_nces_response_strips_markdown_fence():
    raw = '```json\n{"nces_district_id":"9876543"}\n```'
    assert parse_nces_response(raw) == "9876543"


def test_parse_nces_response_invalid_json():
    assert parse_nces_response("not json at all") is None


def test_parse_nces_response_missing_key():
    raw = '{"some_other_key":"1234567"}'
    assert parse_nces_response(raw) is None


def test_parse_nces_response_too_short():
    raw = '{"nces_district_id":"123"}'
    assert parse_nces_response(raw) is None


def test_parse_nces_response_too_long():
    raw = '{"nces_district_id":"12345678"}'
    assert parse_nces_response(raw) is None


def test_parse_nces_response_non_numeric():
    raw = '{"nces_district_id":"ABC1234"}'
    assert parse_nces_response(raw) is None


# ---------------------------------------------------------------------------
# Async unit tests (jina fetch with mocks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jina_fetch_uses_primary_query(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_search(cfg: Any, query: str) -> list[dict]:
        calls.append(query)
        return [{"title": "T", "url": "https://x.com", "content": "NCES District ID: 1234567"}]

    monkeypatch.setattr("staff_finder.nces_enrichment.jina_search", fake_search)

    from staff_finder.config import Settings

    cfg = Settings(jina_api_key="jina_test", openai_api_key="sk_test", enable_jina_cache=False)
    result = await _jina_fetch(cfg, "Acme USD", "CA")

    assert len(calls) == 1  # Only primary query used
    assert "NCES District ID: 1234567" in result


@pytest.mark.asyncio
async def test_jina_fetch_falls_back_when_primary_empty(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_search(cfg: Any, query: str) -> list[dict]:
        calls.append(query)
        if "NCES District ID" in query:
            return []  # Primary returns nothing
        return [{"title": "Fallback", "url": "https://nces.ed.gov/y", "content": "ID: 9999999"}]

    monkeypatch.setattr("staff_finder.nces_enrichment.jina_search", fake_search)

    from staff_finder.config import Settings

    cfg = Settings(jina_api_key="jina_test", openai_api_key="sk_test", enable_jina_cache=False)
    result = await _jina_fetch(cfg, "Unknown USD", "TX")

    assert len(calls) == 2  # Primary + fallback
    assert "Fallback" in result


# ---------------------------------------------------------------------------
# run_enrichment end-to-end with full mocks
# ---------------------------------------------------------------------------


def test_run_enrichment_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_enrichment writes a CSV with district_name, state_abbr, nces_district_id."""

    async def fake_search(cfg: Any, query: str) -> list[dict]:
        return [
            {"title": "NCES Page", "url": "https://nces.ed.gov/z", "content": "NCES District ID: 1234567"}
        ]

    class _FakeMessage:
        content = '{"nces_district_id":"1234567"}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeCompletion:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return _FakeCompletion()

    class _FakeOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = MagicMock()
            self.chat.completions = _FakeCompletions()

    monkeypatch.setattr("staff_finder.nces_enrichment.jina_search", fake_search)
    monkeypatch.setattr("staff_finder.nces_enrichment.AsyncOpenAI", _FakeOpenAI)

    input_csv = tmp_path / "missing_nces_districts.csv"
    input_csv.write_text("district_name,state_abbr\nAcme USD,CA\nNorth Valley SD,TX\n")
    output_csv = tmp_path / "enriched_nces_districts.csv"

    count = run_enrichment(
        input_csv,
        output_csv,
        jina_api_key="jina_test",
        openai_api_key="sk_test",
    )

    assert count == 2
    df = pd.read_csv(output_csv, dtype=object)
    assert list(df.columns) == ["district_name", "state_abbr", "nces_district_id"]
    assert len(df) == 2
    assert set(df["nces_district_id"].tolist()) == {"1234567"}


def test_run_enrichment_null_becomes_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When LLM returns null, nces_district_id is blank in the CSV."""

    async def fake_search(cfg: Any, query: str) -> list[dict]:
        return [{"title": "No data", "url": "https://x.com", "content": "nothing useful"}]

    class _FakeMessage:
        content = '{"nces_district_id":null}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeCompletion:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return _FakeCompletion()

    class _FakeOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.chat = MagicMock()
            self.chat.completions = _FakeCompletions()

    monkeypatch.setattr("staff_finder.nces_enrichment.jina_search", fake_search)
    monkeypatch.setattr("staff_finder.nces_enrichment.AsyncOpenAI", _FakeOpenAI)

    input_csv = tmp_path / "missing.csv"
    input_csv.write_text("district_name,state_abbr\nUnknown USD,NY\n")
    output_csv = tmp_path / "out.csv"

    run_enrichment(input_csv, output_csv, jina_api_key="jk", openai_api_key="ok")

    df = pd.read_csv(output_csv, dtype=object)
    assert pd.isna(df.loc[0, "nces_district_id"]) or df.loc[0, "nces_district_id"] == ""


def test_run_enrichment_missing_api_key(tmp_path: Path) -> None:
    """run_enrichment raises ValueError if API keys are missing."""
    import os

    env_backup = {}
    for key in ("JINA_API_KEY", "STAFF_FINDER_JINA_API_KEY", "OPENAI_API_KEY", "STAFF_FINDER_OPENAI_API_KEY"):
        env_backup[key] = os.environ.pop(key, None)

    try:
        input_csv = tmp_path / "missing.csv"
        input_csv.write_text("district_name,state_abbr\nTest,TX\n")
        with pytest.raises(ValueError, match="Jina API key"):
            run_enrichment(input_csv, tmp_path / "out.csv")
    finally:
        for key, val in env_backup.items():
            if val is not None:
                os.environ[key] = val


def test_run_enrichment_exception_writes_empty_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When enrich_row raises, the row is written with an empty nces_district_id."""

    async def fake_search(cfg: Any, query: str) -> list[dict]:
        raise RuntimeError("network failure")

    monkeypatch.setattr("staff_finder.nces_enrichment.jina_search", fake_search)

    input_csv = tmp_path / "districts.csv"
    input_csv.write_text("district_name,state_abbr\nFailure USD,CA\n")
    output_csv = tmp_path / "out.csv"

    count = run_enrichment(input_csv, output_csv, jina_api_key="jk", openai_api_key="ok")

    assert count == 1
    df = pd.read_csv(output_csv, dtype=object)
    assert len(df) == 1
    assert pd.isna(df.loc[0, "nces_district_id"]) or df.loc[0, "nces_district_id"] == ""
