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

**24 tests** — all deterministic (no network).

## CI

GitHub Actions: `.github/workflows/ci.yml`
- Runs on push/PR to `main`
- Python 3.11 + 3.12 matrix
- Steps: ruff check, ruff format --check, pytest

## CLI Entrypoint

| Command | Purpose |
|---------|---------|
| `staff-finder run <input.csv>` | Discover staff directory URLs for schools |

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
│   ├── cli.py           # Typer CLI entry
│   ├── config.py        # Config loading
│   ├── io_csv.py        # CSV I/O helpers
│   ├── jina_client.py   # Jina API client
│   ├── limiters.py      # Rate limiting
│   ├── models.py        # Data models
│   ├── openai_selector.py  # OpenAI URL selector
│   ├── query_planner.py # Search query construction
│   ├── resolver.py      # Main URL resolution logic
│   ├── shortlist.py     # URL shortlisting
│   └── url_utils.py     # URL parsing helpers
├── tests/               # pytest tests
├── pyproject.toml       # Package + tool config
└── system_prompt.md     # OpenAI system prompt
```
