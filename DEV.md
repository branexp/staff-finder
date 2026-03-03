# DEV.md — staff-finder

## Prerequisites

- **Python** 3.11+ (currently using 3.12.3)
- **Jina API key** — `JINA_API_KEY`
- **OpenAI API key** — `OPENAI_API_KEY`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

## Lint / Format

```bash
ruff check .
ruff check --fix .
ruff format --check .
ruff format .
```

Config: `[tool.ruff]` in pyproject.toml (py311, line-length 100, E/F/I/B/UP rules).

## Tests

```bash
pytest -q          # quick
pytest -v          # verbose
pytest --tb=short  # with short tracebacks
```

**78 tests** — all deterministic (no network).

## CI

GitHub Actions: `.github/workflows/ci.yml`
- Runs on push/PR to `main`
- Python 3.11 + 3.12 matrix
- Steps: ruff check, ruff format --check, pytest

## CLI Entrypoint

| Command | Purpose |
|---------|---------|
| `staff-finder batch start <task> <input.csv>` | Start a batch job for a registered task |
| `staff-finder batch resume <batch_id> --task <task>` | Check status and finalize completed jobs |
| `staff-finder batch tasks` | List available batch tasks |

## Config Precedence

1. CLI flags (highest)
2. Env vars (`JINA_API_KEY`, `OPENAI_API_KEY`, `OPENAI_MODEL`)
3. Config file (`~/.config/staff-finder/config.toml` or `~/.staff-finder.toml`)
4. Defaults

## Key Env Vars

| Variable | Required | Purpose |
|----------|----------|---------|
| `JINA_API_KEY` | Yes | Jina Search/Reader API key |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `OPENAI_MODEL` | No | Model override (default: gpt-4o-mini) |

## Project Structure

```
staff-finder/
├── src/staff_finder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── batch_router.py      # Batch orchestration
│   ├── cli.py               # Typer CLI
│   ├── config.py            # Settings management
│   ├── io_csv.py            # CSV helpers
│   ├── logging_setup.py     # Logging config
│   ├── url_utils.py         # URL sanitization
│   ├── templates/           # Jinja2 prompt templates
│   └── batch_tasks/
│       ├── __init__.py
│       ├── base.py                # BatchTask base class
│       ├── jina_mixin.py          # JinaBatchTask mixin (structured logging + retry)
│       ├── registry.py            # Task registration
│       ├── errors.py              # Error hierarchy
│       ├── dataframe_helpers.py   # Shared DataFrame utilities
│       ├── staff_directory.py     # Staff directory task
│       ├── district_enrichment.py # District enrichment task
│       └── nces_enrichment.py     # NCES enrichment task
├── tests/                   # pytest tests
├── pyproject.toml           # Package + tool config
├── BATCH_TASKS.md           # Batch task framework guide
└── deep-module-analysis.md  # Audit and architecture analysis
```
