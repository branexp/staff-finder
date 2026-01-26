# Usage Guide

## Quick Start

1. **Install the package:**
   ```bash
   pip install -e .
   ```

2. **Set up your API keys:**
   ```bash
   export OPENAI_API_KEY="sk-your-openai-key"
   export JINA_API_KEY="your-jina-key"  # Optional but recommended
   ```

3. **Run the tool:**
   ```bash
   staff-finder example_schools.csv
   ```

## Detailed Usage

### Input CSV Format

Your CSV file must contain at least a `name` column. Optional columns include `city` and `state`:

```csv
name,city,state
Lincoln High School,Portland,Oregon
Washington Elementary,Seattle,Washington
Roosevelt Middle School,San Francisco,California
```

### Command Line Options

```bash
staff-finder INPUT_CSV [OPTIONS]
```

**Options:**
- `-o, --output PATH` - Output CSV file path (default: adds `_with_urls` suffix)
- `--jina-api-key TEXT` - Jina API key (or use `JINA_API_KEY` env var)
- `--openai-api-key TEXT` - OpenAI API key (required, or use `OPENAI_API_KEY` env var)
- `--openai-model TEXT` - OpenAI model to use (default: `gpt-4o-mini`)
- `--max-concurrent INTEGER` - Max concurrent requests (default: 5)
- `-v, --verbose` - Enable verbose logging
- `--help` - Show help message

### Examples

**Basic usage:**
```bash
staff-finder schools.csv
```

**With custom output file:**
```bash
staff-finder schools.csv -o results.csv
```

**With verbose logging:**
```bash
staff-finder schools.csv -v
```

**With custom concurrency:**
```bash
staff-finder schools.csv --max-concurrent 10
```

**Using a different OpenAI model:**
```bash
staff-finder schools.csv --openai-model gpt-4o
```

## Output Format

The tool creates a new CSV file with all original columns plus:

- `staff_url` - The discovered staff directory URL (or None if not found)
- `confidence` - Confidence level: `high`, `medium`, or `low`
- `reasoning` - Brief explanation of why this URL was selected

Example output:

```csv
name,city,state,staff_url,confidence,reasoning
Lincoln High School,Portland,Oregon,https://www.pps.net/lincoln/staff,high,Official school domain with clear staff directory path
Washington Elementary,Seattle,Washington,https://www.seattleschools.org/washington/staff,high,Matches school name and contains staff directory
Roosevelt Middle School,San Francisco,California,,,"No suitable staff directory URL found in results"
```

## API Keys

### OpenAI API Key (Required)
Get your API key from [OpenAI Platform](https://platform.openai.com/api-keys).

The tool uses OpenAI's reasoning models to intelligently select the best staff directory URL from search results. Recommended models:
- `gpt-4o-mini` (default) - Fast and cost-effective
- `gpt-4o` - Higher quality reasoning (more expensive)

### Jina API Key (Optional but Recommended)
Get your API key from [Jina AI](https://jina.ai/).

Jina provides the search results. While optional, using an API key provides:
- Better rate limits
- More reliable results
- Access to advanced search features

## Error Handling

The tool handles errors gracefully:

1. **Missing API keys** - Clear error message with instructions
2. **Invalid CSV** - Validates required columns and provides feedback
3. **Network errors** - Retries and logs failures
4. **Individual failures** - Continues processing other schools

Failed schools will have `None` for `staff_url` and an error message in the `reasoning` column.

## Performance Tips

1. **Adjust concurrency** - Use `--max-concurrent` to balance speed vs. API rate limits:
   - Lower (1-3) for strict rate limits
   - Higher (10-20) for faster processing with premium API tiers

2. **Use verbose mode** - Add `-v` to see progress and identify issues early

3. **Batch processing** - For large datasets, consider splitting into smaller batches

4. **Model selection** - Use `gpt-4o-mini` (default) for most cases; upgrade to `gpt-4o` only if accuracy is critical

## Troubleshooting

**"OpenAI API key is required"**
- Set the `OPENAI_API_KEY` environment variable or use `--openai-api-key`

**"No search results found"**
- Check your internet connection
- Verify the school name is spelled correctly
- Try adding a Jina API key for better results

**"Rate limit exceeded"**
- Reduce `--max-concurrent` value
- Add delays between batches
- Upgrade your API tier

**"No suitable staff directory URL found"**
- The school might not have a public staff directory
- Try searching manually to verify
- Consider updating the school name or adding more location details

## Programmatic Usage

You can also use the tool as a Python library:

```python
import asyncio
from staff_finder import StaffFinder

async def main():
    # Initialize the finder
    finder = StaffFinder(
        openai_api_key="sk-your-key",
        jina_api_key="your-jina-key",
        openai_model="gpt-4o-mini",
        max_concurrent=5
    )
    
    # Process a single school
    school = {
        "name": "Lincoln High School",
        "city": "Portland",
        "state": "Oregon"
    }
    result = await finder.find_staff_url(school)
    print(result)
    
    # Process multiple schools
    schools = [
        {"name": "Lincoln High School", "city": "Portland", "state": "Oregon"},
        {"name": "Washington Elementary", "city": "Seattle", "state": "Washington"}
    ]
    results = await finder.find_staff_urls_batch(schools)
    print(results)

asyncio.run(main())
```

## Testing

Run the test suite:

```bash
pytest tests/ -v
```

Or test individual components:

```bash
pytest tests/test_basic.py -v
```
