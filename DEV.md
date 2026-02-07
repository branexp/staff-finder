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
pip install -e '.[dev]'
```

## Lint / Format

```bash
# Check
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format check
ruff format --check .

# Format fix
ruff format .
```

**Config:** `pyproject.toml` — line-length 100, target py311, rules: E, F, I, B, UP.

**Current status:** 7 lint errors on `giga/config-precedence` branch (1 auto-fixable). Main branch may differ.

## Tests

```bash
pytest
```

**Current: 24 tests, all passing** (on `giga/config-precedence` branch).
- `tests/test_basic.py` — 15 tests (core functionality)
- `tests/test_config_precedence.py` — 4 tests (config loading)
- `tests/test_networkless.py` — 5 tests (offline/mocked tests)

Uses `respx` for HTTP mocking, `pytest-asyncio` for async tests.

## Type Check

No mypy/pyright configured.

## Smoke Test

```bash
# CLI help
staff-finder --help
staff-finder run --help

# Dry run with example CSV (requires API keys)
staff-finder run example_schools.csv --output test_output.csv
```

## CI

**None** — no GitHub Actions workflows yet. (Task card exists for adding CI.)

## Key Env Vars

| Variable | Required | Purpose |
|----------|----------|---------|
| `JINA_API_KEY` | Yes | Jina Reader + Search API key |
| `OPENAI_API_KEY` | Yes | OpenAI API key (classification) |
| `OPENAI_MODEL` | No | Model override (default: gpt-4o-mini) |

## Branches

- `main` — stable baseline
- `giga/config-precedence` — config loading refactor (active)
- `giga/typer-cli` — Typer CLI implementation (needs merge, PR #4)
- `giga/ruff` — linting setup
- `giga/repo-hygiene` — .gitignore + cleanup
- `giga/concurrency-limiters` — rate limiting for Jina/OpenAI

**Note:** Multiple feature branches exist that need to be merged to main. See task cards in Tasks.md.

## Project Structure

```
staff_finder/
  cli.py              # Typer CLI app
  finder.py           # Core staff directory URL discovery
  config.py           # Configuration (env/file/flags precedence)
  jina_client.py      # Jina Reader + Search client
  openai_client.py    # OpenAI classification client
tests/
  test_basic.py
  test_config_precedence.py
  test_networkless.py
system_prompt.md      # Classification prompt for OpenAI
example_schools.csv   # Example input
```
