"""Tests for the NcesEnrichmentTask batch task."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from staff_finder.batch_tasks import get_task, list_tasks
from staff_finder.batch_tasks.utils import (
    normalize_domain,
    parse_json_response,
    require_column,
    resolve_value,
    strip_json_fence,
    validate_nces_id,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_nces_enrichment_task_is_registered():
    assert "nces_enrichment" in list_tasks()
    task = get_task("nces_enrichment")
    assert task.__class__.__name__ == "NcesEnrichmentTask"


# ---------------------------------------------------------------------------
# Utils: validate_nces_id
# ---------------------------------------------------------------------------


def test_validate_nces_id_valid():
    assert validate_nces_id("1234567") == "1234567"


def test_validate_nces_id_null():
    assert validate_nces_id(None) is None


def test_validate_nces_id_empty():
    assert validate_nces_id("") is None


def test_validate_nces_id_too_short():
    assert validate_nces_id("123") is None


def test_validate_nces_id_too_long():
    assert validate_nces_id("12345678") is None


def test_validate_nces_id_non_numeric():
    assert validate_nces_id("ABC1234") is None


# ---------------------------------------------------------------------------
# Utils: strip_json_fence
# ---------------------------------------------------------------------------


def test_strip_json_fence_no_fence():
    assert strip_json_fence('{"key":"val"}') == '{"key":"val"}'


def test_strip_json_fence_with_fence():
    raw = '```json\n{"key":"val"}\n```'
    assert strip_json_fence(raw) == '{"key":"val"}'


# ---------------------------------------------------------------------------
# Utils: parse_json_response
# ---------------------------------------------------------------------------


def test_parse_json_response_valid():
    result = parse_json_response('{"nces_district_id":"1234567"}')
    assert result == {"nces_district_id": "1234567"}


def test_parse_json_response_null_input():
    assert parse_json_response(None) is None


def test_parse_json_response_empty():
    assert parse_json_response("") is None


def test_parse_json_response_invalid_json():
    assert parse_json_response("not json") is None


def test_parse_json_response_strips_fence():
    raw = '```json\n{"nces_district_id":"9876543"}\n```'
    result = parse_json_response(raw)
    assert result == {"nces_district_id": "9876543"}


# ---------------------------------------------------------------------------
# Utils: normalize_domain
# ---------------------------------------------------------------------------


def test_normalize_domain_strips_www():
    assert normalize_domain("https://www.example.com") == "example.com"


def test_normalize_domain_no_scheme():
    assert normalize_domain("example.com") == "example.com"


def test_normalize_domain_none():
    assert normalize_domain(None) is None


# ---------------------------------------------------------------------------
# Utils: require_column
# ---------------------------------------------------------------------------


def test_require_column_found():
    df = pd.DataFrame([{"District_Name": "Acme USD"}])
    col = require_column(df, "district_name", "district")
    assert col == "District_Name"


def test_require_column_missing():
    df = pd.DataFrame([{"other_col": "value"}])
    with pytest.raises(ValueError, match="Missing required column"):
        require_column(df, "district_name", "district")


# ---------------------------------------------------------------------------
# NcesEnrichmentTask.build_jina_query
# ---------------------------------------------------------------------------


def test_nces_build_jina_query():
    task = get_task("nces_enrichment")
    row = pd.Series({"district_name": "Acme USD", "state_abbr": "CA"})
    query = task.build_jina_query(row)
    assert '"Acme USD"' in query
    assert '"CA"' in query
    assert "NCES District ID" in query


def test_nces_build_fallback_query():
    from staff_finder.batch_tasks.nces_enrichment import NcesEnrichmentTask

    task = NcesEnrichmentTask()
    row = pd.Series({"district_name": "Acme USD", "state_abbr": "CA"})
    query = task.build_fallback_query(row)
    assert '"Acme USD"' in query
    assert '"CA"' in query
    assert "site:nces.ed.gov" in query
    assert "site:publicschoolreview.com" in query


# ---------------------------------------------------------------------------
# NcesEnrichmentTask.postprocess_data
# ---------------------------------------------------------------------------


def test_nces_postprocess_valid_id(tmp_path: Path):
    task = get_task("nces_enrichment")
    original_df = pd.DataFrame([{"district_name": "Acme USD", "state_abbr": "CA"}])
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": '{"nces_district_id":"1234567"}',
            }
        ]
    )
    output_csv = tmp_path / "out.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)

    assert result.output_csv == output_csv
    assert result.rows_succeeded == 1
    assert result.rows_failed == 0
    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "nces_district_id"] == "1234567"


def test_nces_postprocess_null_id(tmp_path: Path):
    task = get_task("nces_enrichment")
    original_df = pd.DataFrame([{"district_name": "Unknown USD", "state_abbr": "NY"}])
    merged_df = pd.DataFrame(
        [{"source_index": 0, "status": "success", "output_content": '{"nces_district_id":null}'}]
    )
    output_csv = tmp_path / "out.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)

    assert result.rows_succeeded == 0
    assert result.rows_failed == 1
    saved = pd.read_csv(output_csv, dtype=object)
    assert pd.isna(saved.loc[0, "nces_district_id"])


def test_nces_postprocess_failed_status(tmp_path: Path):
    task = get_task("nces_enrichment")
    original_df = pd.DataFrame([{"district_name": "Acme USD", "state_abbr": "CA"}])
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "failed",
                "output_content": '{"nces_district_id":"1234567"}',
            }
        ]
    )
    output_csv = tmp_path / "out.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)

    assert result.rows_succeeded == 0
    assert result.rows_failed == 1
    saved = pd.read_csv(output_csv, dtype=object)
    assert pd.isna(saved.loc[0, "nces_district_id"])


# ---------------------------------------------------------------------------
# NcesEnrichmentTask.validate_input
# ---------------------------------------------------------------------------


def test_nces_validate_input_valid():
    task = get_task("nces_enrichment")
    df = pd.DataFrame([{"district_name": "Acme USD", "state_abbr": "CA"}])
    assert task.validate_input(df) == []


def test_nces_validate_input_missing_columns():
    task = get_task("nces_enrichment")
    df = pd.DataFrame([{"district_name": "Acme USD"}])
    errors = task.validate_input(df)
    assert any("state_abbr" in e for e in errors)


# ---------------------------------------------------------------------------
# Utils: resolve_value
# ---------------------------------------------------------------------------


def test_resolve_value_first_alias():
    row = pd.Series({"district_name": "Acme USD", "district": "Other"})
    assert resolve_value(row, "district_name", "district") == "Acme USD"


def test_resolve_value_fallback_alias():
    row = pd.Series({"district": "Acme USD"})
    assert resolve_value(row, "district_name", "district") == "Acme USD"


def test_resolve_value_missing_all():
    row = pd.Series({"other": "value"})
    assert resolve_value(row, "district_name", "district") == ""


def test_resolve_value_skips_nan():
    row = pd.Series({"district_name": float("nan"), "district": "Acme USD"})
    assert resolve_value(row, "district_name", "district") == "Acme USD"


def test_resolve_value_skips_empty_string():
    row = pd.Series({"district_name": "", "district": "Acme USD"})
    assert resolve_value(row, "district_name", "district") == "Acme USD"


# ---------------------------------------------------------------------------
# NcesEnrichmentTask.fetch_row_content fallback
# ---------------------------------------------------------------------------


def test_nces_fetch_row_content_uses_fallback_when_primary_empty(monkeypatch):
    """fetch_row_content() should try the fallback query when primary returns nothing."""
    from staff_finder.batch_tasks.nces_enrichment import NcesEnrichmentTask

    task = NcesEnrichmentTask()
    calls: list[str] = []

    def fake_fetch(query: str, *, num_results: int = 5) -> str:
        calls.append(query)
        # Primary (contains "NCES District ID") returns empty; fallback returns content
        if "NCES District ID" in query:
            return ""
        return "fallback content"

    monkeypatch.setattr(task, "fetch_jina_content", fake_fetch)
    row = pd.Series({"district_name": "Test USD", "state_abbr": "TX"})
    result = task.fetch_row_content(row)

    assert len(calls) == 2
    assert result == "fallback content"


def test_nces_fetch_row_content_skips_fallback_when_primary_succeeds(monkeypatch):
    """fetch_row_content() should not call the fallback when primary returns content."""
    from staff_finder.batch_tasks.nces_enrichment import NcesEnrichmentTask

    task = NcesEnrichmentTask()
    calls: list[str] = []

    def fake_fetch(query: str, *, num_results: int = 5) -> str:
        calls.append(query)
        return "primary content"

    monkeypatch.setattr(task, "fetch_jina_content", fake_fetch)
    row = pd.Series({"district_name": "Test USD", "state_abbr": "TX"})
    result = task.fetch_row_content(row)

    assert len(calls) == 1
    assert result == "primary content"
