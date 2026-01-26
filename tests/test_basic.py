"""Basic tests for Staff Finder."""

import pytest
import pandas as pd
from pathlib import Path
from staff_finder import StaffFinder, JinaSearchClient, OpenAISelector


# Get the repository root directory
REPO_ROOT = Path(__file__).parent.parent


def test_imports():
    """Test that all modules can be imported."""
    assert StaffFinder is not None
    assert JinaSearchClient is not None
    assert OpenAISelector is not None


def test_jina_client_init():
    """Test Jina client initialization."""
    client = JinaSearchClient()
    assert client is not None
    assert client.base_url == "https://s.jina.ai"


def test_jina_parse_response():
    """Test Jina response parsing."""
    client = JinaSearchClient()
    
    # Test with sample markdown response
    sample_response = """
Title: School Staff Directory
URL: https://example.edu/staff
Description: Complete listing of all staff members

Title: Faculty Page
URL: https://example.org/faculty
Description: Meet our faculty team
"""
    
    results = client._parse_jina_response(sample_response, max_results=10)
    assert len(results) == 2
    assert results[0]["title"] == "School Staff Directory"
    assert results[0]["url"] == "https://example.edu/staff"
    assert "staff members" in results[0]["description"]


def test_staff_finder_init():
    """Test StaffFinder initialization."""
    # This should not raise an error even without API keys for Jina
    # (OpenAI will fail without key, but we're just testing initialization structure)
    try:
        finder = StaffFinder(jina_api_key="test", openai_api_key="test")
        assert finder is not None
        assert finder.max_concurrent == 5
    except ValueError:
        # Expected if OpenAI client validates the key format
        pass


def test_example_csv_format():
    """Test that example CSV is properly formatted."""
    csv_path = REPO_ROOT / "example_schools.csv"
    df = pd.read_csv(csv_path)
    assert "name" in df.columns
    assert "city" in df.columns
    assert "state" in df.columns
    assert len(df) > 0


@pytest.mark.asyncio
async def test_openai_json_parsing_with_markdown():
    """Test OpenAI response parsing with markdown code blocks."""
    from staff_finder.openai_selector import OpenAISelector
    from unittest.mock import AsyncMock, MagicMock
    
    # Mock the OpenAI client
    selector = OpenAISelector.__new__(OpenAISelector)
    selector.model = "gpt-4o-mini"
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    
    # Test with markdown-wrapped JSON
    mock_response.choices[0].message.content = """```json
{
    "selected_index": 1,
    "selected_url": "https://example.edu/staff",
    "confidence": "high",
    "reasoning": "Official school domain"
}
```"""
    
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    selector.client = mock_client
    
    result = await selector.select_best_url(
        "Test School",
        "City",
        "State",
        [{"url": "https://example.edu/staff", "title": "Staff", "description": "Staff directory"}]
    )
    
    assert result is not None
    assert result["url"] == "https://example.edu/staff"
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_openai_json_parsing_plain():
    """Test OpenAI response parsing with plain JSON."""
    from staff_finder.openai_selector import OpenAISelector
    from unittest.mock import AsyncMock, MagicMock
    
    selector = OpenAISelector.__new__(OpenAISelector)
    selector.model = "gpt-4o-mini"
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    
    # Test with plain JSON (no markdown)
    mock_response.choices[0].message.content = """{
    "selected_index": 2,
    "selected_url": "https://school.org/faculty",
    "confidence": "medium",
    "reasoning": "Contains faculty information"
}"""
    
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    selector.client = mock_client
    
    result = await selector.select_best_url(
        "Test School",
        "City",
        "State",
        [
            {"url": "https://example.com/news", "title": "News", "description": "School news"},
            {"url": "https://school.org/faculty", "title": "Faculty", "description": "Faculty page"}
        ]
    )
    
    assert result is not None
    assert result["url"] == "https://school.org/faculty"
    assert result["confidence"] == "medium"


@pytest.mark.asyncio
async def test_openai_no_suitable_url():
    """Test OpenAI response when no suitable URL is found."""
    from staff_finder.openai_selector import OpenAISelector
    from unittest.mock import AsyncMock, MagicMock
    
    selector = OpenAISelector.__new__(OpenAISelector)
    selector.model = "gpt-4o-mini"
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    
    # Response with selected_index = 0 (no suitable URL)
    mock_response.choices[0].message.content = """{
    "selected_index": 0,
    "selected_url": null,
    "confidence": "low",
    "reasoning": "No staff directory found in results"
}"""
    
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    selector.client = mock_client
    
    result = await selector.select_best_url(
        "Test School",
        "City",
        "State",
        [{"url": "https://example.com/news", "title": "News", "description": "School news"}]
    )
    
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
