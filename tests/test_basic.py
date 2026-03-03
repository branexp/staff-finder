"""Basic tests for Staff Finder."""

from pathlib import Path

import pandas as pd
import pytest

# Get the repository root directory
REPO_ROOT = Path(__file__).parent.parent


def test_imports():
    """Test that core modules can be imported."""
    from staff_finder import (
        ConfigError,
        Settings,
        load_settings,
    )

    assert ConfigError is not None
    assert load_settings is not None
    assert Settings is not None


def test_config_defaults():
    """Test Settings instantiation."""
    from staff_finder.config import Settings

    cfg = Settings()
    # Just verify settings are accessible (actual values may differ from defaults due to env vars)
    assert cfg.max_concurrent_schools >= 1
    assert cfg.candidates_for_selection >= 1
    assert isinstance(cfg.enable_jina_cache, bool)


def test_example_csv_format():
    """Test that example CSV is properly formatted."""
    csv_path = REPO_ROOT / "example_schools.csv"
    df = pd.read_csv(csv_path)
    assert "name" in df.columns
    assert "city" in df.columns
    assert "state" in df.columns
    assert len(df) > 0


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

    df = pd.DataFrame({"name": ["School A"], "staff_directory_url": ["https://example.com"]})
    url_col, _, _ = ensure_output_columns(df)

    assert url_col == "staff_directory_url"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
