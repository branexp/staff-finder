"""Basic tests for Staff Finder."""

import pytest
import pandas as pd
from staff_finder import StaffFinder, JinaSearchClient, OpenAISelector


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
    df = pd.read_csv("example_schools.csv")
    assert "name" in df.columns
    assert "city" in df.columns
    assert "state" in df.columns
    assert len(df) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
