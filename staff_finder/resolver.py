"""School staff directory resolver."""

from __future__ import annotations

from .config import Settings  # type: ignore
from .jina_client import search as jina_search  # type: ignore
from .models import School, SelectionResult  # type: ignore
from .openai_selector import (  # type: ignore
    load_system_prompt,
    parse_gpt_response,
    pick_best_url_async,
)
from .query_planner import build_queries  # type: ignore
from .shortlist import round_robin_union  # type: ignore


async def resolve_for_school_async(cfg: Settings, school: School) -> SelectionResult:
    """Resolve the staff directory URL for a school.
    
    Args:
        cfg: Application settings
        school: School to find staff directory for
        
    Returns:
        SelectionResult with url, confidence, and reasoning
    """
    if not school.name:
        return SelectionResult(url="NOT_FOUND", reasoning="Missing school name")

    # 1) Jina search over built queries
    per_query_results: list[list[dict]] = []
    for q in build_queries(cfg, school):
        try:
            per_query_results.append(await jina_search(cfg, q))
        except Exception:
            per_query_results.append([])

    candidates = round_robin_union(per_query_results, limit=cfg.candidates_for_selection)
    if not candidates:
        return SelectionResult(url="NOT_FOUND", reasoning="No search results found")

    # 2) OpenAI arbiter
    system_instructions = load_system_prompt(cfg.system_prompt_path)
    try:
        raw = await pick_best_url_async(cfg, system_instructions, school, candidates)
        return parse_gpt_response(raw)
    except Exception as e:
        return SelectionResult(url="ERROR_NOT_FOUND", reasoning=str(e))
