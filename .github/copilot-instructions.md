# Copilot Instructions for staff-finder

## Project Overview
`staff-finder` is a Python CLI for discovering staff directory URLs for K-12 schools.

It is optimized for scale and cost:
- Uses **Jina Search API** to fetch web search results.
- Uses **OpenAI Batch API** to analyze candidates asynchronously.
- Targets high-volume CSV workflows where batch processing reduces cost vs real-time calls.

Primary workflow:
1. Read school or district records from CSV.
2. Run search preprocessing (Jina).
3. Build batch prompts from Jinja2 templates.
4. Submit/monitor OpenAI batch jobs.
5. Postprocess outputs back into enriched CSVs.

## Architecture
Code lives under `src/staff_finder/`.

Core modules:
- `cli.py`: Typer CLI entrypoint (`staff-finder ...`).
- `config.py`: settings loading and precedence.
- `batch_router.py`: orchestration for `batch start/resume/tasks` flows.
- `io_csv.py`: CSV read/write helpers.
- `url_utils.py`: URL normalization/sanitization.
- `logging_setup.py`: logging configuration bootstrap.

Batch task framework (`src/staff_finder/batch_tasks/`):
- `base.py`: `BatchTask` abstractions and preprocess/postprocess contracts.
- `jina_mixin.py`: `JinaBatchTask` with Jina fetch logic, retries, and structured preprocess logs.
- `registry.py`: task registration and lookup.
- `errors.py`: shared error taxonomy.
- `dataframe_helpers.py`: reusable DataFrame and parsing helpers.

Task implementations:
- `staff_directory.py`
- `district_enrichment.py`
- `nces_enrichment.py`

Prompt templates:
- `src/staff_finder/templates/*.j2`
- Templates use separated system/user prompt blocks and row interpolation.

Public task API is intentionally narrow via `batch_tasks/__init__.py` exports (9 symbols).
Task modules are imported there for registration side-effects.

## Coding Conventions
Follow repository standards from `pyproject.toml` and project docs:

- Python: **3.11+**.
- Line length: **100**.
- Lint: `ruff` with `E/F/I/B/UP` rules.
- Prefer explicit type hints on public functions/methods.
- Keep functions small and deterministic where feasible.

Logging:
- Use module-level loggers (`logger = logging.getLogger(__name__)`).
- Preserve structured logging patterns used in preprocessing code.

Error handling:
- Reuse taxonomy from `batch_tasks/errors.py`:
  - `ValidationError`
  - `TransientError`
  - `NotFoundError`
  - `ProcessingError`
- Avoid ad-hoc exception classes when these categories fit.

Configuration precedence (must be preserved):
1. CLI flags
2. Environment variables
3. Config file (`~/.config/staff-finder/config.toml`, then `~/.staff-finder.toml`)
4. Defaults

## Creating New Batch Tasks
When adding a task, follow this sequence:

1. Create a task class in `src/staff_finder/batch_tasks/<task_name>.py`.
   - Extend `BatchTask` (or `JinaBatchTask` if web search is required).
2. Register it with `@register_task("<task_name>")`.
3. Add a matching template in `src/staff_finder/templates/<task_name>.j2`.
4. Import the task module in `src/staff_finder/batch_tasks/__init__.py` for registration side-effects.

Implementation guidance:
- Define required input columns and output columns clearly.
- Keep preprocess/postprocess logic robust to partial failures.
- Use shared helpers in `dataframe_helpers.py` before adding new utility code.
- For Jina-backed tasks, follow existing retry and structured logging behavior.

## Testing
Test framework and expectations:
- Use `pytest`.
- Test suite is deterministic and should not require network access.
- Mock Jina and OpenAI clients in unit tests.

Common commands:
- `pytest -q` (quick)
- `pytest -v` (verbose)

When contributing:
- Add tests for new behavior and edge cases.
- Prefer unit tests around preprocess/postprocess boundaries.
- Maintain deterministic fixtures and stable assertions.

## Key Patterns from Audit
Copilot should preserve these design patterns:

- Dependency injection for API keys/configuration values.
- Template Method-style flow in batch task abstractions.
- Narrow public API surface in `batch_tasks/__init__.py`.
- Structured logging during preprocessing operations.

Also preserve current result-quality behavior:
- Multi-query search candidates are merged with round-robin interleaving.

## Important Notes
- `pyproject.toml` is the source of truth for dependencies and tooling config.
- Batch command orchestration depends on external `batchctl` package support.
- Key environment variables:
  - `JINA_API_KEY`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`

Practical Copilot guidance:
- Prefer extending existing abstractions over introducing parallel frameworks.
- Keep CLI UX and option semantics backward-compatible.
- Do not add network-dependent tests.
- When unsure, mirror patterns already used by existing tasks.
