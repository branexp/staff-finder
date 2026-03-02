"""NCES District ID enrichment pipeline.

Reads a CSV of K-12 school districts (district_name, state_abbr), searches for
each district's NCES District ID via Jina AI, then uses an LLM to extract the
exact 7-digit ID.  Results are written to the output CSV incrementally.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from pathlib import Path

import pandas as pd  # type: ignore
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError  # type: ignore
from tenacity import (  # type: ignore
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import Settings
from .jina_client import search as jina_search

_NCES_MODEL = "gpt-5-nano"
_NCES_MAX_RESULTS = 2
_NCES_SYSTEM_TMPL = (
    "You are an expert data extractor. Your task is to find the official 7-digit NCES District ID"
    " for {district_name} in {state_abbr} using ONLY the provided search results."
)
_NCES_USER_TMPL = (
    "Search results:\n{search_text}\n\n"
    "Return ONLY valid JSON in one of these two forms (no markdown, no extra text):\n"
    '  {{"nces_district_id":"1234567"}}\n'
    "or\n"
    '  {{"nces_district_id":null}}\n\n'
    "Rules:\n"
    "- Only return a 7-digit NCES District ID if it is EXPLICITLY stated in the search results.\n"
    "- Do NOT guess, infer, or hallucinate the ID under any circumstances.\n"
    "- If the exact ID is not present in the text, return null."
)


def build_primary_query(district_name: str, state_abbr: str) -> str:
    """Return the primary Jina search query for a district's NCES ID."""
    return f'"{district_name}" school district "{state_abbr}" "NCES District ID"'


def build_fallback_query(district_name: str, state_abbr: str) -> str:
    """Return the fallback Jina search query for a district's NCES ID."""
    return (
        f'"{district_name}" "{state_abbr}" NCES ID'
        " site:nces.ed.gov OR site:publicschoolreview.com"
    )


def _format_search_results(results: list[dict], max_results: int = _NCES_MAX_RESULTS) -> str:
    """Format the first *max_results* Jina results into a plain-text block."""
    chunks: list[str] = []
    for i, result in enumerate(results[:max_results], 1):
        title = (result.get("title") or "").strip()
        url = (result.get("url") or "").strip()
        content = (result.get("content") or "").strip()
        chunks.append(f"[{i}] title: {title}\nurl: {url}\ncontent: {content}")
    return "\n\n".join(chunks)


def parse_nces_response(raw: str | None) -> str | None:
    """Parse LLM JSON response and return the NCES District ID or None."""
    if not raw:
        return None
    text = raw.strip()
    # Strip optional markdown code fence
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("nces_district_id")
    if value is None:
        return None
    return str(value).strip() or None


async def _jina_fetch(cfg: Settings, district_name: str, state_abbr: str) -> str:
    """Fetch search results using primary query, falling back if no results."""
    primary = build_primary_query(district_name, state_abbr)
    results = await jina_search(cfg, primary)
    if not results:
        fallback = build_fallback_query(district_name, state_abbr)
        results = await jina_search(cfg, fallback)
    return _format_search_results(results)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=6),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APITimeoutError)),
)
async def _call_llm(
    openai_api_key: str,
    district_name: str,
    state_abbr: str,
    search_text: str,
    *,
    timeout: float = 30.0,
) -> str | None:
    """Call gpt-5-nano to extract the NCES District ID from search text."""
    system_prompt = _NCES_SYSTEM_TMPL.format(
        district_name=district_name, state_abbr=state_abbr
    )
    user_prompt = _NCES_USER_TMPL.format(search_text=search_text)
    client = AsyncOpenAI(api_key=openai_api_key, timeout=timeout)
    response = await client.chat.completions.create(
        model=_NCES_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = (response.choices[0].message.content or "").strip()
    return parse_nces_response(raw)


async def enrich_row(
    cfg: Settings,
    openai_api_key: str,
    district_name: str,
    state_abbr: str,
) -> str | None:
    """Run the full enrichment pipeline for a single district row."""
    search_text = await _jina_fetch(cfg, district_name, state_abbr)
    if not search_text:
        return None
    return await _call_llm(
        openai_api_key,
        district_name,
        state_abbr,
        search_text,
        timeout=cfg.openai_request_timeout,
    )


async def _run_enrichment_async(
    input_csv: Path,
    output_csv: Path,
    *,
    jina_api_key: str,
    openai_api_key: str,
    max_concurrent: int = 5,
    jina_request_timeout: float = 30.0,
    openai_request_timeout: float = 30.0,
) -> int:
    """Async implementation of the enrichment pipeline.

    Returns the number of rows processed.
    """
    df = pd.read_csv(input_csv, dtype=object)
    # Normalize column names (case-insensitive lookup)
    lower_map = {c.lower(): c for c in df.columns}

    def _col(*aliases: str) -> str:
        for alias in aliases:
            if alias.lower() in lower_map:
                return lower_map[alias.lower()]
        raise ValueError(
            f"Missing required column. Expected one of: {', '.join(aliases)}. "
            f"Found: {', '.join(df.columns)}"
        )

    district_col = _col("district_name", "district", "name")
    state_col = _col("state_abbr", "state", "state_code")

    cfg = Settings(
        jina_api_key=jina_api_key,
        openai_api_key=openai_api_key,
        jina_request_timeout=jina_request_timeout,
        openai_request_timeout=openai_request_timeout,
        enable_jina_cache=False,
    )

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Open output file in write mode and write header immediately
    with open(output_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["district_name", "state_abbr", "nces_district_id"])

        sem = asyncio.Semaphore(max_concurrent)

        async def process_row(district: str, state: str) -> tuple[str, str, str]:
            async with sem:
                nces_id = await enrich_row(cfg, openai_api_key, district, state)
            return district, state, (nces_id or "")

        tasks = [
            asyncio.create_task(
                process_row(
                    "" if pd.isna(row[district_col]) else str(row[district_col]).strip(),
                    "" if pd.isna(row[state_col]) else str(row[state_col]).strip(),
                )
            )
            for _, row in df.iterrows()
        ]

        for task in asyncio.as_completed(tasks):
            district, state, nces_id = await task
            writer.writerow([district, state, nces_id])
            fh.flush()

    return len(tasks)


def run_enrichment(
    input_csv: Path | str,
    output_csv: Path | str,
    *,
    jina_api_key: str | None = None,
    openai_api_key: str | None = None,
    max_concurrent: int = 5,
    jina_request_timeout: float = 30.0,
    openai_request_timeout: float = 30.0,
) -> int:
    """Synchronous entry point for the NCES district ID enrichment pipeline.

    Reads *input_csv* (columns: district_name, state_abbr), searches Jina AI
    for each district's NCES District ID, calls ``gpt-5-nano`` to extract the
    7-digit ID, and writes results incrementally to *output_csv*.

    Returns the number of rows processed.
    """
    resolved_jina_key = jina_api_key or os.getenv("STAFF_FINDER_JINA_API_KEY") or os.getenv(
        "JINA_API_KEY"
    )
    resolved_openai_key = openai_api_key or os.getenv(
        "STAFF_FINDER_OPENAI_API_KEY"
    ) or os.getenv("OPENAI_API_KEY")

    if not resolved_jina_key:
        raise ValueError(
            "Missing Jina API key. Set STAFF_FINDER_JINA_API_KEY or JINA_API_KEY."
        )
    if not resolved_openai_key:
        raise ValueError(
            "Missing OpenAI API key. Set STAFF_FINDER_OPENAI_API_KEY or OPENAI_API_KEY."
        )

    return asyncio.run(
        _run_enrichment_async(
            Path(input_csv),
            Path(output_csv),
            jina_api_key=resolved_jina_key,
            openai_api_key=resolved_openai_key,
            max_concurrent=max_concurrent,
            jina_request_timeout=jina_request_timeout,
            openai_request_timeout=openai_request_timeout,
        )
    )
