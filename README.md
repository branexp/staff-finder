# Staff-Finder

A CLI tool that discovers staff directory URLs for K-12 schools using the OpenAI Batch API for cost-effective processing at scale.

## Overview

Staff-Finder reads a CSV file containing school records (name, city, state, etc.) and finds the most relevant staff directory webpage for each school using a batch workflow.

The tool combines two powerful technologies:

1. **Jina Search API** — Retrieves search engine results (SERP) for each school using multiple query variations
2. **OpenAI Batch API** — Analyzes search results and selects the most relevant staff directory URL at 50% cost savings vs. real-time API

## Features

- **Batch processing** — uses OpenAI Batch API for 50% cost savings
- **Multi-query search** — runs multiple query variations per school and shortlists the best candidates
- **Intelligent selection** — uses OpenAI to pick the best staff directory URL
- **CSV input/output** — fits into existing data workflows
- **Configurable** — concurrency, API keys, model selection

## Installation

```bash
pip install -e .
```

Notes:
- `pyproject.toml` is the source of truth for dependencies.
- `requirements.txt` is provided as a convenience (it should mirror `pyproject.toml`).

## Requirements

- Python 3.11+
- OpenAI API key (required)
- Jina API key (required)

## Usage

### Find Staff Directory URLs

```bash
# Start a batch job
staff-finder batch start staff_directory schools.csv \
  --openai-api-key YOUR_OPENAI_KEY \
  --jina-api-key YOUR_JINA_KEY \
  --openai-model gpt-4o-mini

# Check status / download results when complete
staff-finder batch resume <batch_id> --task staff_directory \
  --openai-api-key YOUR_OPENAI_KEY
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

### List Available Tasks

```bash
staff-finder batch tasks
```

### Config precedence

Settings are loaded using precedence:

1) CLI flags
2) environment variables
3) config file (`~/.config/staff-finder/config.toml`, then `~/.staff-finder.toml`)
4) defaults

### Using environment variables

Minimum required:

```bash
export JINA_API_KEY="your_jina_key"
export OPENAI_API_KEY="your_openai_key"

# Optional (overrides the default model):
export OPENAI_MODEL="gpt-4o-mini"

staff-finder batch start staff_directory schools.csv
```

Preferred (namespaced) env vars are also supported:

```bash
export STAFF_FINDER_JINA_API_KEY="your_jina_key"
export STAFF_FINDER_OPENAI_API_KEY="your_openai_key"
export STAFF_FINDER_OPENAI_MODEL="gpt-4o-mini"
```

Optional local `.env` file (loaded with `override=False`, so real environment variables still win):

```dotenv
JINA_API_KEY=your_jina_key
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
```

For the full list of supported environment variables, see `.env.example`.

### Using a config file

Create `~/.config/staff-finder/config.toml`:

```toml
# Prefer env vars for API keys. If you do store them here, chmod 600.
# openai_api_key = "..."
# jina_api_key = "..."

openai_model = "gpt-4o-mini"
max_concurrent_jina = 10
```

### Batch Commands (OpenAI Batch API)

The batch commands use the non-blocking OpenAI Batch API.
These commands require the optional `batchctl` package to be installed in the same environment.

**List available tasks:**

```bash
staff-finder batch tasks
```

**Start a batch job** (preprocesses, generates JSONL, submits to OpenAI Batch API, returns a batch ID):

```bash
staff-finder batch start staff_directory schools.csv \
  --openai-api-key YOUR_OPENAI_KEY \
  --jina-api-key   YOUR_JINA_KEY
```

Each run is isolated under `.staff_finder/<task>/<task>_<timestamp>/` so concurrent or repeated
invocations with the same input file never overwrite each other's artifacts.

**Resume / poll a batch job** (checks status; downloads and postprocesses results when complete):

```bash
staff-finder batch resume batch_abc123 --task staff_directory \
  --openai-api-key YOUR_OPENAI_KEY
```

Returns immediately with the current status if the batch is still in progress, or writes the
enriched CSV and prints its path when the batch is complete.

## Input CSV Format

The input CSV file should contain at least these columns:

- `school_name` (required) — School name
- `state_abbr` (required) — State abbreviation (e.g. `CA`, `TX`)
- `district_name` (optional) — District name (improves search quality)
- `city` (optional) — City where school is located

Common column aliases are also accepted: `name`, `school`, `state`, `state_code`, `district`.

Example:

```csv
school_name,city,state_abbr
Lincoln High School,Portland,OR
Washington Elementary,Seattle,WA
Roosevelt Middle School,San Francisco,CA
```

See `example_schools.csv` for a sample input file.

## Output

The tool creates (or updates) a CSV with all original columns plus:

- `staff_directory_url` — The discovered staff directory URL (`NOT_FOUND` for failures)
- `confidence` — Confidence level: high, medium, low
- `reasoning` — Brief explanation of why this URL was selected
- `candidate_urls` — JSON list of top candidate URLs considered
- `queries_used` — JSON list of search queries used

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output, -o` | Output CSV file path | Auto-generated |
| `--jina-api-key` | Jina API key | From env/config |
| `--openai-api-key` | OpenAI API key (required) | From env/config |
| `--openai-model` | OpenAI model to use | Task default (`gpt-4o-mini`) |
| `--max-concurrent-jina` | Max concurrent Jina queries | `10` |

## API Keys

### OpenAI API Key
Required. Get your API key from [OpenAI Platform](https://platform.openai.com/api-keys).

### Jina API Key
Required. Get your API key from [Jina AI](https://jina.ai/).

## How It Works

1. **Read Input** — Loads school records from CSV file
2. **Multi-Query Search** — For each school, generates up to 4 query variations and queries Jina Search API
3. **Shortlisting** — Interleaves results from multiple queries using round-robin to get the best candidates
4. **Batch Submit** — Sends all prompts to OpenAI Batch API for cost-effective processing
5. **Postprocess** — Downloads results and writes the enriched CSV with URLs, confidence levels, and reasoning

## License

MIT
