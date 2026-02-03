# Staff-Finder

An async CLI tool that automatically discovers staff directory URLs for K-12 schools.

## Overview

Staff-Finder reads a CSV file containing school records (name, city, state, etc.) and intelligently finds the most relevant staff directory webpage for each school.

The tool combines two powerful technologies:

1. **Jina Search API** — Retrieves search engine results (SERP) for each school
2. **OpenAI Reasoning Model** — Analyzes search results and selects the most relevant staff directory URL

## Features

- 🚀 **Async Processing** — Processes multiple schools concurrently for speed
- 🎯 **Intelligent Selection** — Uses OpenAI to identify the best staff directory page
- 📊 **CSV Input/Output** — Easy to integrate with existing data workflows
- 🔍 **Comprehensive Search** — Leverages Jina's search API for broad coverage
- ⚙️ **Configurable** — Customize concurrency, API keys, and models

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

### Basic Usage

```bash
staff-finder run schools.csv \
  --jina-api-key YOUR_JINA_KEY \
  --openai-api-key YOUR_OPENAI_KEY
```

### With All Options

```bash
staff-finder run schools.csv \
  --output schools_with_urls.csv \
  --jina-api-key YOUR_JINA_KEY \
  --openai-api-key YOUR_OPENAI_KEY \
  --openai-model gpt-5-mini \
  --max-concurrent 5 \
  --verbose
```

### Using Environment Variables

```bash
export JINA_API_KEY="your_jina_key"
export OPENAI_API_KEY="your_openai_key"
staff-finder run schools.csv
```

## Configuration

Config precedence:
1. CLI flags
2. environment variables (plus optional local `.env` for development)
3. config file
4. defaults

Config file locations (low → high precedence):
- `~/.config/staff-finder/config.toml`
- `~/.staff-finder.toml`

Example `config.toml`:

```toml
openai_model = "gpt-5-mini"
max_concurrent_schools = 5

# Prefer env vars for API keys. If you do store them here, chmod 600.
# openai_api_key = "..."
# jina_api_key = "..."
```

## Input CSV Format

The input CSV file should contain at least these columns:

- `name` (required) — School name
- `city` (optional) — City where school is located
- `state` (optional) — State where school is located

Example:

```csv
name,city,state
Lincoln High School,Portland,Oregon
Washington Elementary,Seattle,Washington
Roosevelt Middle School,San Francisco,California
```

See `example_schools.csv` for a sample input file.

## Output

The tool creates (or updates) a CSV with all original columns plus:

- `StaffDirectoryURL` — The discovered staff directory URL (`NOT_FOUND` / `ERROR_NOT_FOUND` for failures)
- `Confidence` — Confidence level: high, medium, low
- `Reasoning` — Brief explanation of why this URL was selected

If your input already contains a URL column (e.g. `staff_directory_url`), Staff-Finder will reuse it.

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output, -o` | Output CSV file path | `{input}_with_urls.csv` |
| `--jina-api-key` | Jina API key | From `JINA_API_KEY` env var |
| `--openai-api-key` | OpenAI API key (required) | From `OPENAI_API_KEY` env var |
| `--openai-model` | OpenAI model to use | `gpt-5-mini` |
| `--max-concurrent` | Max concurrent requests | `5` |
| `--verbose, -v` | Enable verbose logging | `False` |

## API Keys

### OpenAI API Key
Required. Get your API key from [OpenAI Platform](https://platform.openai.com/api-keys).

### Jina API Key
Required. Get your API key from [Jina AI](https://jina.ai/).

## Example

```bash
# Run with example data
export OPENAI_API_KEY="sk-..."
staff-finder run example_schools.csv -v
```

Output:
```
2026-01-26 12:00:00 - staff_finder.cli - INFO - Reading schools from: example_schools.csv
2026-01-26 12:00:00 - staff_finder.cli - INFO - Found 3 schools to process
2026-01-26 12:00:00 - staff_finder.cli - INFO - Starting to find staff directory URLs...
2026-01-26 12:00:01 - staff_finder.processor - INFO - Searching for: Lincoln High School Portland Oregon staff directory
2026-01-26 12:00:02 - staff_finder.processor - INFO - Found 10 search results for Lincoln High School
2026-01-26 12:00:03 - staff_finder.processor - INFO - Selected URL: https://www.pps.net/lincoln/staff (confidence: high)
...
2026-01-26 12:00:10 - staff_finder.cli - INFO - Results saved to: example_schools_with_urls.csv
2026-01-26 12:00:10 - staff_finder.cli - INFO - 
Summary:
  Total schools: 3
  URLs found: 3
  Not found: 0

Confidence levels:
  high: 2
  medium: 1
```

## How It Works

1. **Read Input** — Loads school records from CSV file
2. **Search** — For each school, queries Jina Search API with: `"{school name} {city} {state} staff directory"`
3. **Analyze** — OpenAI analyzes the search results and identifies the most relevant staff directory page based on:
   - URL patterns (contains "staff", "faculty", "directory", etc.)
   - Domain authority (official school domains)
   - Content relevance (actual staff listings vs. job postings)
4. **Output** — Saves results with URLs, confidence levels, and reasoning

## License

MIT