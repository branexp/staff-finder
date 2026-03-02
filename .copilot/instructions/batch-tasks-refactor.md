# Batch Tasks Framework Refactor

**Goal:** Standardize the `batch_tasks/` framework and refactor `nces_enrichment.py` into a proper batch task.

## Overview

The `staff-finder` repo currently has:
- A batch task framework (`batch_tasks/base.py`, `registry.py`, `district_enrichment.py`)
- A standalone `nces_enrichment.py` that bypasses the framework

This refactor will:
1. Standardize and extend the batch task framework
2. Migrate `nces_enrichment.py` to a proper `NcesEnrichmentTask`
3. Add shared utilities, error taxonomy, and task-specific config
4. Create comprehensive documentation

---

## Phase 1: Shared Utilities Module

Create `src/staff_finder/batch_tasks/utils.py` with reusable helpers:

```python
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
```

---

## Phase 2: Error Taxonomy

Create `src/staff_finder/batch_tasks/errors.py`:

```python
"""Shared error taxonomy for batch tasks."""
from __future__ import annotations

from enum import Enum


class BatchTaskError(Exception):
    """Base exception for batch task errors."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or "UNKNOWN_ERROR"


class ValidationError(BatchTaskError):
    """Input validation failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")


class TransientError(BatchTaskError):
    """Transient error that may be retried (429, 5xx, timeout)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="TRANSIENT_ERROR")


class NotFoundError(BatchTaskError):
    """Resource not found (no search results, missing data)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="NOT_FOUND")


class ProcessingError(BatchTaskError):
    """Non-recoverable processing error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="PROCESSING_ERROR")


class ErrorCode(str, Enum):
    """Standardized error codes for batch task results."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    NOT_FOUND = "NOT_FOUND"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    SUCCESS = "SUCCESS"


def is_transient_http_error(exc: BaseException) -> bool:
    """Return True for transient HTTP errors (429, 5xx, timeouts)."""
    try:
        import httpx

        if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            return exc.response.status_code == 429 or (500 <= exc.response.status_code < 600)
    except ImportError:
        pass
    return False
```

---

## Phase 3: Enhanced Base Class

Update `src/staff_finder/batch_tasks/base.py`:

```python
"""Abstract base class for template-driven batch tasks."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd  # type: ignore

from .errors import BatchTaskError

_SYSTEM_START = "{# SYSTEM_PROMPT_START #}"
_SYSTEM_END = "{# SYSTEM_PROMPT_END #}"
_USER_START = "{# USER_PROMPT_START #}"
_USER_END = "{# USER_PROMPT_END #}"


@dataclass
class TaskConfig:
    """Configuration options specific to a batch task."""

    # Override these in subclasses for task-specific defaults
    default_model: str = "gpt-4o-mini"
    max_workers: int = 5
    jina_max_results: int = 5
    jina_max_content_chars: int = 1500


@dataclass
class PreprocessResult:
    """Result container returned by task preprocessors."""

    processed_csv: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostprocessResult:
    """Result container returned by task postprocessors."""

    output_csv: Path
    rows_processed: int
    rows_succeeded: int
    rows_failed: int
    metadata: dict[str, Any] = field(default_factory=dict)


class BatchTask(ABC):
    """Abstract base class for template-driven batch tasks."""

    # Class-level metadata (override in subclasses)
    task_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires_jina: ClassVar[bool] = False
    required_input_columns: ClassVar[list[str]] = []
    output_columns: ClassVar[list[str]] = []

    def __init__(self, config: TaskConfig | None = None) -> None:
        self.config = config or TaskConfig()

    @abstractmethod
    def get_template_path(self) -> Path:
        """Return the absolute path to the task's prompt template file."""

    @abstractmethod
    def preprocess_data(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
    ) -> PreprocessResult:
        """Prepare input data for JSONL generation."""

    @abstractmethod
    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        """Transform reconciled batch outputs and persist final enriched CSV."""

    def validate_input(self, df: pd.DataFrame) -> list[str]:
        """Validate input DataFrame. Returns list of validation errors."""
        errors: list[str] = []
        available = {c.lower() for c in df.columns}

        for col in self.required_input_columns:
            if col.lower() not in available:
                errors.append(f"Missing required column: {col}")

        return errors

    def load_prompt_templates(self) -> tuple[str, str]:
        """Load system/user prompt sections from this task's template file."""
        content = self.get_template_path().read_text(encoding="utf-8")

        system = self._extract_section(content, _SYSTEM_START, _SYSTEM_END, "system")
        user = self._extract_section(content, _USER_START, _USER_END, "user")
        return system, user

    @staticmethod
    def _extract_section(content: str, start: str, end: str, name: str) -> str:
        start_idx = content.find(start)
        end_idx = content.find(end)
        if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
            raise ValueError(
                f"Template is missing a valid {name!r} section delimited by "
                + f"{start!r} and {end!r}"
            )
        inner = content[start_idx + len(start) : end_idx].strip()
        if not inner:
            raise ValueError(f"Template {name!r} section is empty")
        return inner
```

---

## Phase 4: Jina Client Interface

Create `src/staff_finder/batch_tasks/jina_mixin.py`:

```python
"""Mixin for batch tasks that require Jina web search."""
from __future__ import annotations

import os
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import BatchTask, PreprocessResult
from .errors import is_transient_http_error


class JinaBatchTask(BatchTask):
    """Base class for batch tasks that use Jina web search during preprocessing."""

    requires_jina = True

    @abstractmethod
    def build_jina_query(self, row: pd.Series) -> str:
        """Build a Jina search query for a single row. Return empty string to skip."""

    @abstractmethod
    def format_jina_results(self, results: list[Any]) -> str:
        """Format Jina search results into a string for the LLM prompt."""

    def get_jina_api_key(self) -> str:
        """Get Jina API key from environment."""
        key = os.getenv("STAFF_FINDER_JINA_API_KEY") or os.getenv("JINA_API_KEY")
        if not key:
            raise ValueError("Missing Jina API key. Set STAFF_FINDER_JINA_API_KEY or JINA_API_KEY.")
        return key

    def get_jina_client(self) -> Any:
        """Get an authenticated Jina client instance."""
        try:
            from batchctl.core.clients.jina import JinaClient
        except ImportError as e:
            raise RuntimeError(
                "batchctl is required for Jina preprocessing. "
                "Install batchctl in the same Python environment as staff-finder."
            ) from e

        return JinaClient(api_key=self.get_jina_api_key())

    def fetch_jina_content(
        self,
        query: str,
        *,
        num_results: int = 5,
        max_content_chars: int = 1500,
    ) -> str:
        """Fetch and format Jina search results for a single query."""
        if not query:
            return ""

        @retry(
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            retry=retry_if_exception(is_transient_http_error),
        )
        def _fetch() -> str:
            client = self.get_jina_client()
            results = client.search(query, num_results=num_results)
            return self.format_jina_results(results)

        try:
            return _fetch()
        except Exception as e:
            return f"ERROR: {e}"

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

        # Build queries
        df["jina_query"] = df.apply(self.build_jina_query, axis=1)
        df[output_column] = ""

        worker_count = max(1, min(max_workers, 20))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self.fetch_jina_content,
                    str(query),
                    num_results=self.config.jina_max_results,
                    max_content_chars=self.config.jina_max_content_chars,
                ): idx
                for idx, query in df["jina_query"].items()
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    df.at[idx, output_column] = future.result()
                except Exception as e:
                    df.at[idx, output_column] = f"ERROR: {e}"

        df.to_csv(processed_csv, index=False)
        return PreprocessResult(
            processed_csv=processed_csv,
            metadata={"row_count": int(len(df)), "max_workers": worker_count},
        )
```

---

## Phase 5: Refactor `district_enrichment.py`

Update `src/staff_finder/batch_tasks/district_enrichment.py` to use the new utilities and mixin:

```python
"""District enrichment batch task."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd  # type: ignore

from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .errors import ErrorCode
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import normalize_domain, parse_json_response, require_column


@register_task("district_enrichment")
class DistrictEnrichmentTask(JinaBatchTask):
    """Enrich school districts with website URL and acronym."""

    task_name = "district_enrichment"
    description = "Enrich school districts with official website URL and acronym via Jina search."
    required_input_columns = ["district_name", "state_abbr"]
    output_columns = ["acronym", "website_url", "domain"]

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config or TaskConfig(default_model="gpt-4o-mini"))

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "district_enrichment.j2"

    def build_jina_query(self, row: pd.Series) -> str:
        district = "" if pd.isna(row.get("district_name")) else str(row.get("district_name")).strip()
        state = "" if pd.isna(row.get("state_abbr")) else str(row.get("state_abbr")).strip()
        district_part = f'"{district}"' if district else ""
        return f"{district_part} {state} school district official website".strip()

    def format_jina_results(self, results: list) -> str:
        chunks: list[str] = []
        for i, result in enumerate(results, 1):
            title = (getattr(result, "title", None) or "").strip()
            description = (getattr(result, "description", None) or "").strip()
            content = (getattr(result, "content", None) or "").strip()
            content = content[: self.config.jina_max_content_chars]
            url = getattr(result, "url", "").strip()
            chunks.append(
                f"[{i}] title: {title}\nurl: {url}\ndescription: {description}\ncontent: {content}"
            )
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
            output_column="web_content",
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        enriched = original_df.copy()
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

            acronym = payload.get("acronym")
            website_url = payload.get("website_url")

            if website_url and not isinstance(website_url, str):
                website_url = str(website_url)

            if website_url and "://" not in website_url:
                website_url = f"https://{website_url}"

            domain = normalize_domain(website_url)

            if acronym:
                enriched.at[source_index, "acronym"] = str(acronym).strip()
            if website_url:
                enriched.at[source_index, "website_url"] = str(website_url).strip()
            if domain:
                enriched.at[source_index, "domain"] = str(domain).strip()

            rows_succeeded += 1

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

## Phase 6: Create `nces_enrichment` Batch Task

Create `src/staff_finder/batch_tasks/nces_enrichment.py`:

```python
"""NCES District ID enrichment batch task."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd  # type: ignore

from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import parse_json_response, validate_nces_id


@register_task("nces_enrichment")
class NcesEnrichmentTask(JinaBatchTask):
    """Enrich school districts with their 7-digit NCES District ID."""

    task_name = "nces_enrichment"
    description = "Find official 7-digit NCES District ID for school districts via Jina search."
    required_input_columns = ["district_name", "state_abbr"]
    output_columns = ["nces_district_id"]

    # NCES-specific config
    NCES_MODEL = "gpt-5-nano"

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config or TaskConfig(default_model=self.NCES_MODEL))

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "nces_enrichment.j2"

    def build_jina_query(self, row: pd.Series) -> str:
        """Build primary query for NCES District ID."""
        district = "" if pd.isna(row.get("district_name")) else str(row.get("district_name")).strip()
        state = "" if pd.isna(row.get("state_abbr")) else str(row.get("state_abbr")).strip()
        return f'"{district}" school district "{state}" "NCES District ID"'.strip()

    def build_fallback_query(self, row: pd.Series) -> str:
        """Build fallback query if primary returns no results."""
        district = "" if pd.isna(row.get("district_name")) else str(row.get("district_name")).strip()
        state = "" if pd.isna(row.get("state_abbr")) else str(row.get("state_abbr")).strip()
        return (
            f'"{district}" "{state}" NCES ID '
            "site:nces.ed.gov OR site:publicschoolreview.com"
        ).strip()

    def format_jina_results(self, results: list) -> str:
        """Format results with NCES-specific truncation."""
        chunks: list[str] = []
        for i, result in enumerate(results[:2], 1):  # NCES only needs 2 results
            title = (getattr(result, "title", None) or "").strip()
            url = getattr(result, "url", "").strip()
            content = (getattr(result, "content", None) or "").strip()
            content = content[:1500]
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
            output_column="web_content",
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        enriched = original_df.copy()
        if "nces_district_id" not in enriched.columns:
            enriched["nces_district_id"] = pd.NA

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

            nces_id = validate_nces_id(payload.get("nces_district_id"))
            if nces_id:
                enriched.at[source_index, "nces_district_id"] = nces_id
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

## Phase 7: Create NCES Template

Create `src/staff_finder/templates/nces_enrichment.j2`:

```jinja2
{# SYSTEM_PROMPT_START #}
You are an expert data extractor. Your task is to find the official 7-digit NCES District ID for school districts.

Return ONLY valid JSON with this exact schema (no markdown, no backticks, no commentary):
{
  "nces_district_id": "string or null"
}

Rules:
- Only return a 7-digit NCES District ID if it is EXPLICITLY stated in the provided search results.
- Do NOT guess, infer, or hallucinate the ID under any circumstances.
- If the exact ID is not present in the text, return null.
- The ID must be exactly 7 numeric digits.

Example Output:
{
  "nces_district_id": "1234567"
}
{# SYSTEM_PROMPT_END #}

{# USER_PROMPT_START #}
District: {{ record.district_name if record.district_name is defined else record.district }}
State: {{ record.state_abbr if record.state_abbr is defined else record.state }}
Search Query: {{ record.jina_query }}

Jina Search Results:
{{ record.web_content }}

Extract the 7-digit NCES District ID.
{# USER_PROMPT_END #}
```

---

## Phase 8: Update Registry and __init__.py

Update `src/staff_finder/batch_tasks/__init__.py`:

```python
"""Batch tasks for staff-finder."""
from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .errors import (
    BatchTaskError,
    ErrorCode,
    NotFoundError,
    ProcessingError,
    TransientError,
    ValidationError,
)
from .registry import get_task, list_tasks, register_task
from .utils import (
    normalize_domain,
    parse_json_response,
    require_column,
    strip_json_fence,
    validate_nces_id,
)

# Import tasks to trigger registration
from . import district_enrichment  # noqa: F401
from . import nces_enrichment  # noqa: F401

__all__ = [
    # Base classes
    "BatchTask",
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
    "strip_json_fence",
    "validate_nces_id",
]
```

---

## Phase 9: Update CLI

Update `src/staff_finder/cli.py` to:
1. Remove the standalone `enrich-nces` command (now handled via batch)
2. Update `batch start` to accept task-specific model override
3. Add a `batch tasks` command to list available tasks with metadata

Add to `cli.py`:

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
        typer.echo(f"  {name}{jina}")
        typer.echo(f"    {desc}")
        typer.echo()
```

---

## Phase 10: Create Documentation

Create `BATCH_TASKS.md` at the repo root:

````markdown
# Batch Tasks Framework

This document describes the batch task framework in `staff-finder` and how to create new tasks.

## Overview

Batch tasks use OpenAI's Batch API for cost-effective, asynchronous processing of large datasets. Each task defines:

1. **Preprocessing** — Prepare input data (e.g., fetch web content via Jina)
2. **Prompt Template** — System and user prompts for the LLM
3. **Postprocessing** — Transform LLM outputs into the final enriched dataset

## Available Tasks

| Task | Description | Requires Jina |
|------|-------------|---------------|
| `district_enrichment` | Enrich districts with website URL and acronym | Yes |
| `nces_enrichment` | Find official NCES District IDs | Yes |

## Usage

### Start a Batch Job

```bash
staff-finder batch start district_enrichment input.csv
```

### Resume / Check Status

```bash
staff-finder batch resume <batch_id> --task district_enrichment
```

### List Available Tasks

```bash
staff-finder batch tasks
```

## Creating a New Batch Task

### 1. Create the Task Class

Create `src/staff_finder/batch_tasks/my_task.py`:

```python
from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .registry import register_task

@register_task("my_task")
class MyTask(BatchTask):
    task_name = "my_task"
    description = "Description of what this task does."
    required_input_columns = ["column1", "column2"]
    output_columns = ["result_column"]

    def get_template_path(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / "templates" / "my_task.j2"

    def preprocess_data(self, input_csv, work_dir, *, max_workers):
        # Prepare data, return PreprocessResult
        ...

    def postprocess_data(self, merged_df, original_df, output_csv):
        # Transform outputs, return PostprocessResult
        ...
```

### 2. Create the Template

Create `src/staff_finder/templates/my_task.j2`:

```jinja2
{# SYSTEM_PROMPT_START #}
Your system prompt here.
{# SYSTEM_PROMPT_END #}

{# USER_PROMPT_START #}
User prompt with {{ record.column_name }} interpolation.
{# USER_PROMPT_END #}
```

### 3. Register in __init__.py

Add to `src/staff_finder/batch_tasks/__init__.py`:

```python
from . import my_task  # noqa: F401
```

## Task Types

### Simple Task (No Jina)

Extend `BatchTask` directly for tasks that don't need web search:

```python
class SimpleTask(BatchTask):
    requires_jina = False
    # ... implementation
```

### Jina-Based Task

Extend `JinaBatchTask` for tasks that need web search:

```python
from .jina_mixin import JinaBatchTask

class WebSearchTask(JinaBatchTask):
    requires_jina = True
    
    def build_jina_query(self, row):
        return f'"{row["name"]}" official website'
    
    def format_jina_results(self, results):
        # Format results for the prompt
        ...
```

## Task Configuration

Each task accepts a `TaskConfig` with these defaults:

```python
TaskConfig(
    default_model="gpt-4o-mini",  # LLM model for this task
    max_workers=5,                # Concurrent preprocessing workers
    jina_max_results=5,           # Max Jina results per query
    jina_max_content_chars=1500,  # Truncate Jina content
)
```

Override in the task constructor:

```python
def __init__(self, config=None):
    super().__init__(config or TaskConfig(default_model="gpt-5-nano"))
```

## Error Handling

The framework provides a standardized error taxonomy:

- `ValidationError` — Input validation failed
- `TransientError` — Retryable errors (429, 5xx, timeout)
- `NotFoundError` — Resource not found
- `ProcessingError` — Non-recoverable processing error

Use `ErrorCode` enum for result classification:

```python
from .errors import ErrorCode

if success:
    return PostprocessResult(..., metadata={"code": ErrorCode.SUCCESS})
```

## Utilities

Shared utilities in `batch_tasks/utils.py`:

- `require_column(df, *aliases)` — Case-insensitive column lookup
- `strip_json_fence(value)` — Remove markdown code fences
- `normalize_domain(url)` — Extract bare domain from URL
- `parse_json_response(raw)` — Parse JSON from LLM response
- `validate_nces_id(value)` — Validate 7-digit NCES ID

## Testing

Each task should have unit tests for:

1. `validate_input()` — Input column validation
2. `preprocess_data()` — Data preparation logic
3. `postprocess_data()` — Output transformation logic

Use mocked Jina/OpenAI clients for tests.
````

---

## Phase 11: Update batch_router.py

Update `src/staff_finder/batch_router.py` to use the new `PostprocessResult`:

```python
# In resume_batch_task, after calling task.postprocess_data():
result = task.postprocess_data(merged_df, original_df, Path(state.output_csv))

state.merged_csv = str(merged_csv.resolve())
state.completed_at = _utc_now_iso()
_write_state(state)

return ResumeResult(
    status=status_value,
    output_csv=result.output_csv,
    metadata=result.metadata,  # Include rows_succeeded, rows_failed, etc.
)
```

Also update `ResumeResult` dataclass:

```python
@dataclass
class ResumeResult:
    status: str
    output_csv: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## Phase 12: Clean Up

After the refactor is complete:

1. **Remove** `src/staff_finder/nces_enrichment.py` (standalone version)
2. **Remove** the `enrich-nces` CLI command from `cli.py`
3. **Run** `ruff check .` and `ruff format .`
4. **Run** `pytest` to verify nothing is broken
5. **Update** `README.md` to reflect the new batch task commands

---

## Verification Checklist

- [ ] `staff-finder batch tasks` shows both `district_enrichment` and `nces_enrichment`
- [ ] `staff-finder batch start nces_enrichment test.csv` creates a batch
- [ ] `staff-finder batch resume <id> --task nces_enrichment` completes successfully
- [ ] Template files exist at `templates/nces_enrichment.j2` and `templates/district_enrichment.j2`
- [ ] `BATCH_TASKS.md` documentation exists and is accurate
- [ ] No `enrich-nces` command in `staff-finder --help`
- [ ] All imports resolve without errors
- [ ] `ruff check .` passes
- [ ] `pytest` passes (or only fails on pre-existing issues)

---

## File Summary

| Action | File |
|--------|------|
| Create | `src/staff_finder/batch_tasks/utils.py` |
| Create | `src/staff_finder/batch_tasks/errors.py` |
| Create | `src/staff_finder/batch_tasks/jina_mixin.py` |
| Create | `src/staff_finder/batch_tasks/nces_enrichment.py` |
| Create | `src/staff_finder/templates/nces_enrichment.j2` |
| Create | `BATCH_TASKS.md` |
| Update | `src/staff_finder/batch_tasks/base.py` |
| Update | `src/staff_finder/batch_tasks/district_enrichment.py` |
| Update | `src/staff_finder/batch_tasks/__init__.py` |
| Update | `src/staff_finder/batch_tasks/registry.py` (minor, if needed) |
| Update | `src/staff_finder/batch_router.py` |
| Update | `src/staff_finder/cli.py` |
| Remove | `src/staff_finder/nces_enrichment.py` |
