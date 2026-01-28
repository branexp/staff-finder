"""Basic tests for Staff Finder."""

import pytest
import pandas as pd
from pathlib import Path


# Get the repository root directory
REPO_ROOT = Path(__file__).parent.parent


def test_imports():
    """Test that all modules can be imported."""
    from staff_finder import Settings, School, SelectionResult, map_headers, resolve_for_school_async
    assert Settings is not None
    assert School is not None
    assert SelectionResult is not None
    assert map_headers is not None
    assert resolve_for_school_async is not None


def test_config_defaults():
    """Test Settings instantiation."""
    from staff_finder.config import Settings
    cfg = Settings()
    # Just verify settings are accessible (actual values may differ from defaults due to env vars)
    assert cfg.max_concurrent_schools >= 1
    assert cfg.candidates_for_selection >= 1
    assert isinstance(cfg.enable_jina_cache, bool)


def test_school_model():
    """Test School dataclass."""
    from staff_finder.models import School
    school = School(
        name="Test High School",
        district="Test District",
        county="Test County",
        city="Test City",
        state="TX"
    )
    assert school.name == "Test High School"
    assert school.state == "TX"


def test_selection_result_model():
    """Test SelectionResult dataclass."""
    from staff_finder.models import SelectionResult
    result = SelectionResult(
        url="https://example.edu/staff",
        confidence="high",
        reasoning="Official school domain"
    )
    assert result.url == "https://example.edu/staff"
    assert result.confidence == "high"
    assert result.reasoning == "Official school domain"


def test_map_headers():
    """Test CSV header mapping."""
    from staff_finder.models import map_headers
    row = pd.Series({
        "school_name": "Lincoln High School",
        "district_name": "Lincoln USD",
        "city": "Lincoln",
        "state": "CA"
    })
    school = map_headers(row)
    assert school.name == "Lincoln High School"
    assert school.district == "Lincoln USD"
    assert school.city == "Lincoln"
    assert school.state == "CA"


def test_example_csv_format():
    """Test that example CSV is properly formatted."""
    csv_path = REPO_ROOT / "example_schools.csv"
    df = pd.read_csv(csv_path)
    assert "name" in df.columns
    assert "city" in df.columns
    assert "state" in df.columns
    assert len(df) > 0


def test_parse_gpt_response_valid():
    """Test parsing valid GPT response with all fields."""
    from staff_finder.openai_selector import parse_gpt_response
    
    raw = '{"selected_index": 1, "selected_url": "https://example.edu/staff", "confidence": "high", "reasoning": "Official school domain"}'
    result = parse_gpt_response(raw)
    
    assert result.url == "https://example.edu/staff"
    assert result.confidence == "high"
    assert result.reasoning == "Official school domain"


def test_parse_gpt_response_not_found():
    """Test parsing GPT response with null URL."""
    from staff_finder.openai_selector import parse_gpt_response
    
    raw = '{"selected_index": 0, "selected_url": null, "confidence": "low", "reasoning": "No staff directory found"}'
    result = parse_gpt_response(raw)
    
    assert result.url == "NOT_FOUND"
    assert result.confidence == "low"
    assert result.reasoning == "No staff directory found"


def test_parse_gpt_response_empty():
    """Test parsing empty/null response."""
    from staff_finder.openai_selector import parse_gpt_response
    
    result = parse_gpt_response(None)
    assert result.url == "ERROR_NOT_FOUND"
    assert result.reasoning == "No response from model"
    
    result = parse_gpt_response("")
    assert result.url == "ERROR_NOT_FOUND"


def test_parse_gpt_response_malformed():
    """Test parsing malformed response with URL extraction."""
    from staff_finder.openai_selector import parse_gpt_response
    
    raw = 'Here is the URL: https://example.edu/staff-directory and more text'
    result = parse_gpt_response(raw)
    
    assert result.url == "https://example.edu/staff-directory"
    assert result.confidence == "low"
    assert "malformed" in result.reasoning.lower()


def test_sanitize_url():
    """Test URL sanitization."""
    from staff_finder.url_utils import sanitize_url
    
    # Valid URL
    assert sanitize_url("https://example.edu/staff") == "https://example.edu/staff"
    
    # Remove fragments
    assert sanitize_url("https://example.edu/staff#section") == "https://example.edu/staff"
    
    # Normalize scheme/host
    assert sanitize_url("HTTPS://EXAMPLE.EDU/Staff") == "https://example.edu/Staff"
    
    # Invalid URLs
    assert sanitize_url(None) is None
    assert sanitize_url("") is None
    assert sanitize_url("not-a-url") is None
    assert sanitize_url("ftp://example.com") is None


def test_round_robin_union():
    """Test round-robin URL deduplication."""
    from staff_finder.shortlist import round_robin_union
    
    list1 = [{"url": "https://a.com"}, {"url": "https://b.com"}]
    list2 = [{"url": "https://c.com"}, {"url": "https://a.com"}]  # duplicate
    
    result = round_robin_union([list1, list2], limit=3)
    urls = [r["url"] for r in result]
    
    assert len(result) == 3
    assert "https://a.com" in urls
    assert "https://c.com" in urls
    assert "https://b.com" in urls


def test_build_queries():
    """Test query building for search."""
    from staff_finder.query_planner import build_queries
    from staff_finder.config import Settings
    from staff_finder.models import School
    
    cfg = Settings()
    cfg.max_queries_per_school = 3
    
    school = School(
        name="Lincoln High School",
        district="Lincoln USD",
        county="",
        city="Lincoln",
        state="CA"
    )
    
    queries = build_queries(cfg, school)
    
    assert len(queries) <= 3
    assert all("Lincoln High School" in q for q in queries)
    assert any("staff directory" in q.lower() for q in queries)


def test_ensure_output_columns():
    """Test that output columns are created properly."""
    from staff_finder.io_csv import ensure_output_columns
    
    df = pd.DataFrame({"name": ["School A"], "city": ["City A"]})
    url_col, conf_col, reason_col = ensure_output_columns(df)
    
    assert url_col == "StaffDirectoryURL"
    assert conf_col == "Confidence"
    assert reason_col == "Reasoning"
    assert "StaffDirectoryURL" in df.columns
    assert "Confidence" in df.columns
    assert "Reasoning" in df.columns


def test_ensure_output_columns_existing():
    """Test that existing URL column is recognized."""
    from staff_finder.io_csv import ensure_output_columns
    
    df = pd.DataFrame({
        "name": ["School A"],
        "staff_directory_url": ["https://example.com"]
    })
    url_col, _, _ = ensure_output_columns(df)
    
    assert url_col == "staff_directory_url"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
