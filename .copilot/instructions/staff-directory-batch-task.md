# Staff Directory Finder Batch Task Refactor

**Goal:** Migrate the `staff-finder run` command (real-time school staff directory discovery) into a batch task that uses OpenAI Batch API for cost-effective processing at scale.

## Overview

### Current State

The `run` command processes schools in real-time:
- Uses async workers with concurrent Jina searches + LLM calls
- Multiple Jina queries per school via `query_planner.py`
- Candidate shortlisting via `shortlist.py`'s `round_robin_union()`
- Immediate results with progress bar
- Higher cost (standard API rates)

### Target State

A new `staff_directory` batch task that:
- Uses OpenAI Batch API for 50% cost savings
- Extends the framework with multi-query preprocessing support
- Migrates shortlisting logic into preprocessing
- Uses a two-stage template approach
- Produces same output schema + additional optional columns
- Model configurable per-run

---

## Decisions Made

| Topic | Decision |
|-------|----------|
| Cost vs. immediacy | Cost savings worth it — full migration to batch |
| Multi-query support | Extend framework to support multiple Jina queries per row natively |
| Shortlisting | Migrate into batch task preprocessing |
| Output schema | Match existing + add optional columns |
| Retry/resume | Use existing batch lifecycle (batch start/resume) |
| Model | Configurable per-run |
| Error handling | Use error taxonomy from `batch_tasks/errors.py` |
| Deprecation | Remove `staff-finder run` command entirely |
| Template | Two-stage approach |
| Task integration | Independent tasks with explicit handoffs |

---

## Phase 1: Extend TaskConfig for Model Override

Update `src/staff_finder/batch_tasks/base.py` to support per-run model configuration:

```python
@dataclass
class TaskConfig:
    """Configuration options specific to a batch task."""

    # Override these in subclasses for task-specific defaults
    default_model: str = "gpt-4o-mini"
    max_workers: int = 5
    jina_max_results: int = 5
    jina_max_content_chars: int = 1500

    # Multi-query support
    jina_queries_per_row: int = 1  # Number of queries to run per input row
    jina_results_per_query: int = 5  # Results per individual query
```

The `start_batch_task` function in `batch_router.py` already accepts an `openai_model` parameter. No changes needed there.

---

## Phase 2: Extend JinaBatchTask for Multi-Query Support

Update `src/staff_finder/batch_tasks/jina_mixin.py` to support multiple queries per row:

### 2.1 Add Abstract Method for Query Building

```python
@abstractmethod
def build_jina_queries(self, row: pd.Series) -> list[str]:
    """Build a list of Jina search queries for a single row.

    Return an empty list to skip this row.
    Default implementation calls build_jina_query for single-query compatibility.
    """
    query = self.build_jina_query(row)
    return [query] if query else []
```

### 2.2 Add Shortlisting Method

```python
def shortlist_candidates(
    self,
    per_query_results: list[list[Any]],
    limit: int,
) -> list[dict]:
    """Interleave candidates from multiple queries using round-robin.

    This prevents one query's results from dominating the shortlist.
    Returns a list of candidate dicts with url, title, content.
    """
    out: list[dict] = []
    seen_urls: set[str] = set()
    i = 0

    while len(out) < limit:
        added = False
        for results in per_query_results:
            if i < len(results):
                result = results[i]
                url = (getattr(result, "url", "") or "").strip().lower()
                if url and url not in seen_urls:
                    out.append({
                        "title": (getattr(result, "title", None) or "").strip(),
                        "url": url,
                        "content": (getattr(result, "content", None) or "").strip(),
                    })
                    seen_urls.add(url)
                    if len(out) >= limit:
                        break
                added = True
        if not added:
            break
        i += 1

    return out
```

### 2.3 Add Multi-Query Row Fetch

```python
def fetch_row_content_multi_query(self, row: pd.Series) -> str:
    """Fetch and format Jina content for a row using multiple queries.

    Runs all queries from build_jina_queries(), shortlists results,
    and formats for the LLM prompt.
    """
    queries = self.build_jina_queries(row)
    if not queries:
        return ""

    per_query_results: list[list[Any]] = []

    for query in queries:
        if not query:
            per_query_results.append([])
            continue

        try:
            client = self.get_jina_client()
            results = client.search(query, num_results=self.config.jina_results_per_query)
            per_query_results.append(results)
        except Exception:
            per_query_results.append([])

    # Shortlist candidates from all queries
    candidates = self.shortlist_candidates(
        per_query_results,
        limit=self.config.jina_max_results,
    )

    return self.format_jina_results(candidates)
```

### 2.4 Update preprocess_with_jina

```python
def preprocess_with_jina(
    self,
    input_csv: Path,
    work_dir: Path,
    *,
    max_workers: int,
    output_column: str = "web_content",
) -> PreprocessResult:
    """Generic preprocessing flow for Jina-based tasks."""
    df = pd.read_csv(input_csv, dtype=object)

    work_dir.mkdir(parents=True, exist_ok=True)
    processed_csv = work_dir / f"{input_csv.stem}_preprocessed.csv"

    # Build queries (stored for template reference)
    df["jina_queries"] = df.apply(
        lambda row: json.dumps(self.build_jina_queries(row)),
        axis=1,
    )
    df[output_column] = ""

    worker_count = max(1, min(max_workers, 20))

    # Choose fetch method based on multi-query setting
    fetch_func = (
        self.fetch_row_content_multi_query
        if self.config.jina_queries_per_row > 1
        else self.fetch_row_content
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_func, row): idx for idx, row in df.iterrows()
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                df.at[idx, output_column] = future.result()
            except Exception:
                df.at[idx, output_column] = ""

    df.to_csv(processed_csv, index=False)
    return PreprocessResult(
        processed_csv=processed_csv,
        metadata={"row_count": int(len(df)), "max_workers": worker_count},
    )
```

---

## Phase 3: Create StaffDirectoryTask

Create `src/staff_finder/batch_tasks/staff_directory.py`:

```python
"""Staff directory URL discovery batch task."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd  # type: ignore

from .base import PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import parse_json_response, require_column, resolve_value

# Canonical column aliases for school input
_SCHOOL_ALIASES = ("school_name", "name", "school")
_DISTRICT_ALIASES = ("district_name", "district")
_CITY_ALIASES = ("city", "city_name")
_STATE_ALIASES = ("state_abbr", "state", "state_code")
_COUNTY_ALIASES = ("county_name", "county")


def _build_query_variations(
    school: str,
    district: str,
    city: str,
    state: str,
    max_queries: int,
) -> list[str]:
    """Build multiple query variations for staff directory discovery.

    Ordered by expected signal quality.
    """
    where = " ".join([p for p in (city, state) if p])
    q_school = f'"{school}"' if school else ""
    q_district = f'"{district}"' if district else ""

    candidates = [
        f'{q_school} "staff directory" {where}'.strip(),
        f'{q_school} ("faculty & staff" OR "faculty and staff" OR "staff") {where}'.strip(),
        f'{q_school} ("our staff" OR "staff list" OR "faculty directory" OR "directory") {where}'.strip(),
    ]

    if district:
        candidates.append(
            f'{q_district} ("staff directory" OR "directory") {q_school} {where}'.strip()
        )

    # Dedupe and clean
    seen, out = set(), []
    for q in candidates:
        q = re.sub(r"\s+", " ", q).strip()
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
        if len(out) >= max_queries:
            break

    return out


@register_task("staff_directory")
class StaffDirectoryTask(JinaBatchTask):
    """Discover staff directory URLs for schools."""

    task_name = "staff_directory"
    description = "Find staff directory URLs for K-12 schools via multi-query Jina search."
    required_input_columns = ["school_name", "state_abbr"]
    output_columns = [
        "staff_directory_url",
        "confidence",
        "reasoning",
        # Optional additional columns
        "candidate_urls",
        "queries_used",
    ]

    # Use two-stage template approach
    STAGE_1_MODEL = "gpt-4o-mini"  # Candidate filtering
    STAGE_2_MODEL = "gpt-4o-mini"  # Final selection

    def __init__(self, config: TaskConfig | None = None) -> None:
        cfg = config or TaskConfig(
            default_model=self.STAGE_1_MODEL,
            max_workers=10,
            jina_max_results=12,  # Final candidates for LLM
            jina_queries_per_row=4,  # Query variations per school
            jina_results_per_query=5,  # Results per query before shortlist
        )
        super().__init__(cfg)

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "staff_directory.j2"

    def get_stage2_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "staff_directory_stage2.j2"

    def validate_input(self, df: pd.DataFrame) -> list[str]:
        """Validate input, accepting common column name aliases."""
        errors: list[str] = []
        try:
            require_column(df, *_SCHOOL_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        try:
            require_column(df, *_STATE_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        return errors

    def build_jina_queries(self, row: pd.Series) -> list[str]:
        """Build multiple query variations for staff directory discovery."""
        school = resolve_value(row, *_SCHOOL_ALIASES)
        district = resolve_value(row, *_DISTRICT_ALIASES)
        city = resolve_value(row, *_CITY_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)

        if not school:
            return []

        return _build_query_variations(
            school=school,
            district=district,
            city=city,
            state=state,
            max_queries=self.config.jina_queries_per_row,
        )

    def format_jina_results(self, results: list) -> str:
        """Format shortlisted candidates for the LLM prompt.

        Expects a list of dicts (from shortlist_candidates), not raw Jina results.
        """
        chunks: list[str] = []
        for i, candidate in enumerate(results, 1):
            title = (candidate.get("title", "") or "").strip()
            url = (candidate.get("url", "") or "").strip()
            content = (candidate.get("content", "") or "").strip()
            content = content[: self.config.jina_max_content_chars]
            chunks.append(f"[{i}] title: {title}\nurl: {url}\ncontent: {content}")
        return "\n\n".join(chunks)

    def preprocess_data(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
    ) -> PreprocessResult:
        df = pd.read_csv(input_csv, dtype=object)

        # Validate input
        errors = self.validate_input(df)
        if errors:
            raise ValueError("; ".join(errors))

        return self.preprocess_with_jina(
            input_csv,
            work_dir,
            max_workers=max_workers,
            output_column="candidates",
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        from .utils import strip_json_fence
        import json

        enriched = original_df.copy()

        # Ensure all output columns exist
        for col in self.output_columns:
            if col not in enriched.columns:
                enriched[col] = pd.NA

        status_col = "status" if "status" in merged_df.columns else None
        rows_succeeded = 0
        rows_failed = 0

        for _, row in merged_df.iterrows():
            try:
                source_index = int(row.get("source_index"))
            except Exception:
                rows_failed += 1
                continue

            if source_index < 0 or source_index >= len(enriched):
                rows_failed += 1
                continue

            if status_col and str(row.get(status_col, "")).lower() != "success":
                rows_failed += 1
                continue

            raw = row.get("output_content")
            payload = parse_json_response(raw)
            if payload is None:
                rows_failed += 1
                continue

            # Extract main fields
            url = payload.get("staff_directory_url") or payload.get("selected_url")
            confidence = payload.get("confidence")
            reasoning = payload.get("reasoning", "")

            # Handle NOT_FOUND vs null
            if url and url.lower() in ("not_found", "null", "none", ""):
                url = "NOT_FOUND"

            # Extract optional fields
            candidate_urls = payload.get("candidate_urls", [])
            queries_used = payload.get("queries_used", [])

            # Write to enriched
            if url:
                enriched.at[source_index, "staff_directory_url"] = str(url).strip()
            if confidence:
                enriched.at[source_index, "confidence"] = str(confidence).strip()
            if reasoning:
                enriched.at[source_index, "reasoning"] = str(reasoning).strip()
            if candidate_urls:
                enriched.at[source_index, "candidate_urls"] = json.dumps(candidate_urls)
            if queries_used:
                enriched.at[source_index, "queries_used"] = json.dumps(queries_used)

            if url and url != "NOT_FOUND":
                rows_succeeded += 1
            else:
                rows_failed += 1

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_csv(output_csv, index=False)

        return PostprocessResult(
            output_csv=output_csv,
            rows_processed=len(enriched),
            rows_succeeded=rows_succeeded,
            rows_failed=rows_failed,
        )
```

---

## Phase 4: Create Two-Stage Templates

### Stage 1: Candidate Evaluation Template

Create `src/staff_finder/templates/staff_directory.j2`:

```jinja2
{# SYSTEM_PROMPT_START #}
You are a staff directory URL evaluator for K-12 schools.

Your task is to analyze candidate URLs and select the single best staff directory URL.

**Ranking priorities (highest to lowest):**
1. School's own staff directory page (preferred)
2. District staff directory page scoped to this specific school
3. District-wide staff directory page
4. State education directory page

**Reject:**
- Social media links (Facebook, Twitter, LinkedIn, etc.)
- Aggregator sites (GreatSchools, Niche, PublicSchoolReview, etc.)
- Generic pages without staff listings
- Job postings / employment listings

Return ONLY valid JSON with this exact schema:
{
  "staff_directory_url": "string or null",
  "confidence": "high|medium|low",
  "reasoning": "brief explanation of selection",
  "candidate_urls": ["list of top 3 candidate URLs considered"]
}

**Confidence levels:**
- `high`: Direct match, clearly the school's staff directory
- `medium`: Likely match, district page or partial information
- `low`: Uncertain, best available option

If no suitable candidate exists, set `staff_directory_url` to null.
{# SYSTEM_PROMPT_END #}

{# USER_PROMPT_START #}
School: {{ record.school_name if record.school_name is defined else (record.name if record.name is defined else record.school) }}
{% if record.district_name is defined or record.district is defined %}
District: {{ record.district_name if record.district_name is defined else record.district }}
{% endif -%}
{% if record.city is defined %}
City: {{ record.city }}
{% endif -%}
State: {{ record.state_abbr if record.state_abbr is defined else (record.state if record.state is defined else record.state_code) }}

Queries Used:
{{ record.jina_queries }}

Candidate Results (shortlisted from multiple queries):
{{ record.candidates }}

Select the best staff directory URL for this school.
{# USER_PROMPT_END #}
```

### Stage 2: Validation Template (Optional, for high-value runs)

Create `src/staff_finder/templates/staff_directory_stage2.j2`:

```jinja2
{# SYSTEM_PROMPT_START #}
You are a staff directory URL validator.

Given a school and a proposed staff directory URL, validate whether it is correct.

Return ONLY valid JSON:
{
  "is_valid": true|false,
  "corrected_url": "string or null",
  "reasoning": "brief explanation"
}

Rules:
- If the URL appears to be a valid staff directory, set `is_valid: true`
- If the URL is incorrect but you can identify the correct one, set `is_valid: false` and provide `corrected_url`
- If no valid directory exists, set both `is_valid: false` and `corrected_url: null`
{# SYSTEM_PROMPT_END #}

{# USER_PROMPT_START #}
School: {{ record.school_name }}
District: {{ record.district_name }}
State: {{ record.state_abbr }}

Proposed URL: {{ record.staff_directory_url }}

Validate this URL.
{# USER_PROMPT_END #}
```

---

## Phase 5: Update CLI

### 5.1 Remove `run` Command

Delete the `run` command function and its helper functions from `cli.py`:
- Remove `run` command
- Remove `run_async` function
- Remove `_worker` function
- Remove `_flush_results` function
- Remove `_default_output_path` function
- Remove `NULLISH` constant

Keep imports that are used by batch commands.

### 5.2 Add `batch tasks` Command

Add a command to list available tasks:

```python
@batch_app.command("tasks")
def batch_tasks() -> None:
    """List available batch tasks with descriptions."""
    tasks = list_tasks()
    if not tasks:
        typer.echo("No batch tasks registered.")
        raise typer.Exit(0)

    for name in tasks:
        task = get_task(name)
        desc = getattr(task, "description", "(no description)")
        jina = " [Jina]" if getattr(task, "requires_jina", False) else ""
        cols = getattr(task, "output_columns", [])
        typer.echo(f"  {name}{jina}")
        typer.echo(f"    {desc}")
        if cols:
            typer.echo(f"    Output: {', '.join(cols)}")
        typer.echo()
```

### 5.3 Update `batch start` for Model Override

Ensure the `batch start` command accepts and passes through the `--openai-model` flag. This should already be implemented, but verify it works correctly.

---

## Phase 6: Update Registry and Exports

Update `src/staff_finder/batch_tasks/__init__.py`:

```python
"""Batch tasks for staff-finder."""

# Import tasks to trigger registration
from . import (
    district_enrichment,  # noqa: F401
    nces_enrichment,  # noqa: F401
    staff_directory,  # noqa: F401
)
from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .errors import (
    BatchTaskError,
    ErrorCode,
    NotFoundError,
    ProcessingError,
    TransientError,
    ValidationError,
)
from .jina_mixin import JinaBatchTask
from .registry import get_task, list_tasks, register_task
from .utils import (
    normalize_domain,
    parse_json_response,
    require_column,
    resolve_value,
    strip_json_fence,
    validate_nces_id,
)

__all__ = [
    # Base classes
    "BatchTask",
    "JinaBatchTask",
    "TaskConfig",
    "PreprocessResult",
    "PostprocessResult",
    # Errors
    "BatchTaskError",
    "ErrorCode",
    "NotFoundError",
    "ProcessingError",
    "TransientError",
    "ValidationError",
    # Registry
    "get_task",
    "list_tasks",
    "register_task",
    # Utilities
    "normalize_domain",
    "parse_json_response",
    "require_column",
    "resolve_value",
    "strip_json_fence",
    "validate_nces_id",
]
```

---

## Phase 7: Remove Obsolete Code

Delete files that are no longer needed after migration:

1. **Delete `src/staff_finder/resolver.py`** — Logic moved to batch task
2. **Delete `src/staff_finder/query_planner.py`** — Logic moved to `build_jina_queries()`
3. **Delete `src/staff_finder/shortlist.py`** — Logic moved to `shortlist_candidates()`
4. **Delete `src/staff_finder/openai_selector.py`** — Logic moved to template
5. **Delete `src/staff_finder/limiters.py`** — No longer needed (batch API handles rate limiting)
6. **Delete `src/staff_finder/models.py`** — School model can be inlined or kept for utilities
7. **Delete `src/staff_finder/system_prompt.md`** — Replaced by template

Keep these files (still used by batch tasks):
- `config.py` — Settings and config loading
- `io_csv.py` — CSV utilities
- `logging_setup.py` — Logging configuration
- `url_utils.py` — URL sanitization utilities
- `jina_client.py` — Async Jina client (may be used by other code)
- `batch_router.py` — Batch lifecycle management

---

## Phase 8: Update Tests

### 8.1 Update `test_batch_tasks.py`

Add tests for `StaffDirectoryTask`:

```python
import pytest
from staff_finder.batch_tasks import StaffDirectoryTask, TaskConfig


def test_staff_directory_task_registration():
    from staff_finder.batch_tasks import get_task
    task = get_task("staff_directory")
    assert task is not None
    assert task.task_name == "staff_directory"


def test_staff_directory_builds_multiple_queries():
    task = StaffDirectoryTask()
    row = pd.Series({
        "school_name": "Lincoln Elementary",
        "district_name": "Springfield Public Schools",
        "city": "Springfield",
        "state_abbr": "IL",
    })
    queries = task.build_jina_queries(row)
    assert len(queries) >= 2
    assert any("staff directory" in q.lower() for q in queries)


def test_staff_directory_shortlisting():
    task = StaffDirectoryTask()
    # Mock results from multiple queries
    per_query = [
        [{"url": "http://a.com", "title": "A", "content": "..."},
         {"url": "http://b.com", "title": "B", "content": "..."}],
        [{"url": "http://c.com", "title": "C", "content": "..."},
         {"url": "http://a.com", "title": "A dupe", "content": "..."}],  # dupe URL
    ]
    shortlisted = task.shortlist_candidates(per_query, limit=5)
    urls = [c["url"] for c in shortlisted]
    # Round-robin: a.com from query 0, c.com from query 1, b.com from query 0
    assert urls[0] == "http://a.com"
    assert urls[1] == "http://c.com"
    assert urls[2] == "http://b.com"
    assert "http://a.com" not in urls[1:]  # No dupes
```

### 8.2 Remove Obsolete Tests

Delete tests for removed modules:
- Remove tests for `resolver.py`
- Remove tests for `query_planner.py`
- Remove tests for `shortlist.py`
- Remove tests for `run` command

---

## Phase 9: Update Documentation

### 9.1 Update BATCH_TASKS.md

Add `staff_directory` to the available tasks table:

```markdown
## Available Tasks

| Task | Description | Requires Jina | Output Columns |
|------|-------------|---------------|----------------|
| `district_enrichment` | Enrich districts with website URL and acronym | Yes | acronym, website_url, domain |
| `nces_enrichment` | Find official NCES District IDs | Yes | nces_district_id |
| `staff_directory` | Find staff directory URLs for schools | Yes | staff_directory_url, confidence, reasoning, candidate_urls, queries_used |
```

### 9.2 Update README.md

Remove documentation for `staff-finder run` and replace with batch commands:

```markdown
## Usage

### Find Staff Directory URLs

```bash
# Start a batch job
staff-finder batch start staff_directory schools.csv --openai-model gpt-4o-mini

# Check status / download results
staff-finder batch resume <batch_id> --task staff_directory
```

### Enrich Districts

```bash
staff-finder batch start district_enrichment districts.csv
staff-finder batch resume <batch_id> --task district_enrichment
```

### Find NCES IDs

```bash
staff-finder batch start nces_enrichment districts.csv
staff-finder batch resume <batch_id> --task nces_enrichment
```
```

---

## Phase 10: Clean Up

After all changes:

1. Run `ruff check .` and fix any issues
2. Run `ruff format .`
3. Run `pytest` and ensure all tests pass
4. Verify CLI with `staff-finder --help`
5. Verify batch commands with `staff-finder batch tasks`

---

## Verification Checklist

- [ ] `staff-finder batch tasks` shows `staff_directory` task
- [ ] `staff-finder batch start staff_directory test.csv` creates a batch
- [ ] `staff-finder batch resume <id> --task staff_directory` completes successfully
- [ ] Template exists at `templates/staff_directory.j2`
- [ ] Multi-query preprocessing works (4 queries per school, shortlisted to 12 candidates)
- [ ] Output CSV has columns: `staff_directory_url`, `confidence`, `reasoning`, `candidate_urls`, `queries_used`
- [ ] `staff-finder run` command is removed (not in `--help`)
- [ ] Obsolete files are deleted (resolver.py, query_planner.py, shortlist.py, etc.)
- [ ] All tests pass
- [ ] `ruff check .` passes

---

## File Summary

| Action | File |
|--------|------|
| Create | `src/staff_finder/batch_tasks/staff_directory.py` |
| Create | `src/staff_finder/templates/staff_directory.j2` |
| Create | `src/staff_finder/templates/staff_directory_stage2.j2` |
| Update | `src/staff_finder/batch_tasks/__init__.py` |
| Update | `src/staff_finder/batch_tasks/base.py` |
| Update | `src/staff_finder/batch_tasks/jina_mixin.py` |
| Update | `src/staff_finder/cli.py` |
| Update | `tests/test_batch_tasks.py` |
| Update | `BATCH_TASKS.md` |
| Update | `README.md` |
| Delete | `src/staff_finder/resolver.py` |
| Delete | `src/staff_finder/query_planner.py` |
| Delete | `src/staff_finder/shortlist.py` |
| Delete | `src/staff_finder/openai_selector.py` |
| Delete | `src/staff_finder/limiters.py` |
| Delete | `src/staff_finder/models.py` |
| Delete | `src/staff_finder/system_prompt.md` |
| Delete | Tests for removed modules |

---

## Implementation Order

1. **Phase 1-2:** Extend framework (base.py, jina_mixin.py) — foundation
2. **Phase 3-4:** Create task and templates — core implementation
3. **Phase 5-6:** Update CLI and registry — wire it up
4. **Phase 7:** Remove obsolete code — cleanup
5. **Phase 8-9:** Tests and docs — verification
6. **Phase 10:** Final verification

This order ensures each phase builds on completed work and can be tested incrementally.
