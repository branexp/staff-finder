# Batch Tasks Framework

This document describes the batch task framework in `staff-finder` and how to create new tasks.

## Overview

Batch tasks use OpenAI's Batch API for cost-effective, asynchronous processing of large datasets. Each task defines:

1. **Preprocessing** — Prepare input data (e.g., fetch web content via Jina)
2. **Prompt Template** — System and user prompts for the LLM
3. **Postprocessing** — Transform LLM outputs into the final enriched dataset

## Available Tasks

| Task | Description | Requires Jina | Output Columns |
|------|-------------|---------------|----------------|
| `district_enrichment` | Enrich districts with website URL and acronym | Yes | acronym, website_url, domain |
| `nces_enrichment` | Find official NCES District IDs | Yes | nces_district_id |
| `staff_directory` | Find staff directory URLs for schools | Yes | staff_directory_url, confidence, reasoning, candidate_urls, queries_used |

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
