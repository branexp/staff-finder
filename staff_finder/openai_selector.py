"""OpenAI-based URL selection with structured output."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type  # type: ignore
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APITimeoutError  # type: ignore

from .config import Settings  # type: ignore
from .models import School, SelectionResult  # type: ignore
from .url_utils import sanitize_url, URL_RE  # type: ignore


def load_system_prompt(path: str) -> str:
    """Load system prompt from file or return default."""
    p = Path(path)
    if p.exists():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    # fallback default
    return (
        "# Staff Directory Evaluator — System Instructions\n\n"
        "You analyze up to 5–12 SERP candidates (title, url, content) for a K-12 school and return the single best staff directory URL.\n"
        "Prefer the school's own site; otherwise the district page scoped to the school. Avoid socials/aggregators.\n"
        "Output exactly one JSON object: {\"selected_index\": <int>, \"selected_url\": \"<url or null>\", \"confidence\": \"high|medium|low\", \"reasoning\": \"<brief explanation>\"}\n"
    )


def _truncate_content(content: str, max_chars: int) -> str:
    """Truncate content to avoid exceeding model context limits."""
    if not content or len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


def _payload(school: School, candidates: List[Dict], max_content_chars: int) -> Dict:
    """Build the payload for OpenAI request."""
    # Truncate content to prevent context length issues
    truncated_candidates = [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "content": _truncate_content(c.get("content", ""), max_content_chars)
        }
        for c in candidates
    ]
    return {
        "school": {
            "district_name": school.district,
            "county_name": school.county,
            "city": school.city,
            "state": school.state,
            "school_name": school.name
        },
        "candidates": truncated_candidates
    }


def _response_text(resp) -> str:
    """Extract text from OpenAI responses API response."""
    # openai responses API (responses.create) compatible
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()
    pieces = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", "") == "message":
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    pieces.append(getattr(c, "text", ""))
    return "".join(pieces).strip()


def parse_gpt_response(raw: Optional[str]) -> SelectionResult:
    """Parse GPT response into a SelectionResult with url, confidence, and reasoning."""
    if not raw:
        return SelectionResult(url="ERROR_NOT_FOUND", reasoning="No response from model")
    
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            url_value = obj.get("selected_url")
            url = sanitize_url(url_value) if url_value else None
            return SelectionResult(
                url=url if (url and url != "NOT_FOUND") else "NOT_FOUND",
                confidence=obj.get("confidence"),
                reasoning=obj.get("reasoning", "")
            )
    except json.JSONDecodeError:
        pass
    
    # Fallback: try to extract URL from malformed response
    m = URL_RE.search(raw or "")
    url_value = m.group(0) if m else None
    url = sanitize_url(url_value) if url_value else None
    return SelectionResult(
        url=url if url else "NOT_FOUND",
        confidence="low",
        reasoning="Extracted from malformed response"
    )


# JSON schema for structured output with confidence and reasoning
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_index": {"type": "integer"},
        "selected_url": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasoning": {"type": "string"}
    },
    "required": ["selected_index", "selected_url", "confidence", "reasoning"],
    "additionalProperties": False
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=6),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APITimeoutError)),
)
async def pick_best_url_async(cfg: Settings, system_instructions: str, school: School, candidates: List[Dict]) -> str:
    """Use OpenAI to select the best staff directory URL from candidates."""
    client = AsyncOpenAI(timeout=cfg.openai_request_timeout)
    resp = await client.responses.create(
        model=cfg.openai_model,
        instructions=system_instructions,
        input=json.dumps(_payload(school, candidates, cfg.max_content_chars), ensure_ascii=False),
        reasoning={"effort": cfg.openai_reasoning_effort},
        text={
            "verbosity": cfg.openai_verbosity,
            "format": {
                "type": "json_schema",
                "name": "StaffDirectoryResult",
                "schema": _RESPONSE_SCHEMA,
                "strict": True
            }
        },
    )
    return _response_text(resp)
