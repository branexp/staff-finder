from pathlib import Path

import pandas as pd

from staff_finder.batch_tasks import get_task, list_tasks


def test_district_enrichment_task_is_registered():
    assert "district_enrichment" in list_tasks()
    task = get_task("district_enrichment")
    assert task.__class__.__name__ == "DistrictEnrichmentTask"


def test_nces_enrichment_task_is_registered():
    assert "nces_enrichment" in list_tasks()
    task = get_task("nces_enrichment")
    assert task.__class__.__name__ == "NcesEnrichmentTask"


def test_district_template_sections_load():
    task = get_task("district_enrichment")
    system_template, user_template = task.load_prompt_templates()
    assert "Return ONLY valid JSON" in system_template
    assert "{{ record.web_content }}" in user_template


def test_nces_template_sections_load():
    task = get_task("nces_enrichment")
    system_template, user_template = task.load_prompt_templates()
    assert "nces_district_id" in system_template
    assert "{{ record.web_content }}" in user_template


def test_district_postprocess_writes_expected_columns(tmp_path: Path):
    task = get_task("district_enrichment")
    original_df = pd.DataFrame(
        [
            {"district_name": "Acme Public Schools", "state_abbr": "TX"},
            {"district_name": "North Valley School District", "state_abbr": "CA"},
            {"district_name": "Unknown District", "state_abbr": "NY"},
        ]
    )
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": ('{"acronym":"APS","website_url":"https://www.acmeisd.org"}'),
            },
            {
                "source_index": 1,
                "status": "success",
                "output_content": '{"acronym":"NVSD","website_url":"https://northvalley.k12.ca.us"}',
            },
            {
                "source_index": 2,
                "status": "success",
                "output_content": '{"acronym":"UD","website_url":null}',
            },
        ]
    )

    output_csv = tmp_path / "district_enriched.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)
    assert result.output_csv == output_csv
    assert result.rows_processed == 3
    assert result.rows_succeeded == 3
    assert result.rows_failed == 0

    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "acronym"] == "APS"
    assert saved.loc[0, "website_url"] == "https://www.acmeisd.org"
    assert saved.loc[0, "domain"] == "acmeisd.org"
    assert saved.loc[1, "acronym"] == "NVSD"
    assert saved.loc[1, "website_url"] == "https://northvalley.k12.ca.us"
    assert saved.loc[1, "domain"] == "northvalley.k12.ca.us"
    # When website_url is null, domain must also be null
    assert saved.loc[2, "acronym"] == "UD"
    assert pd.isna(saved.loc[2, "website_url"])
    assert pd.isna(saved.loc[2, "domain"])


def test_nces_postprocess_writes_expected_columns(tmp_path: Path):
    task = get_task("nces_enrichment")
    original_df = pd.DataFrame(
        [
            {"district_name": "Acme USD", "state_abbr": "CA"},
            {"district_name": "Unknown USD", "state_abbr": "TX"},
        ]
    )
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": '{"nces_district_id":"1234567"}',
            },
            {
                "source_index": 1,
                "status": "success",
                "output_content": '{"nces_district_id":null}',
            },
        ]
    )

    output_csv = tmp_path / "nces_enriched.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)
    assert result.output_csv == output_csv
    assert result.rows_processed == 2
    assert result.rows_succeeded == 1
    assert result.rows_failed == 1

    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "nces_district_id"] == "1234567"
    assert pd.isna(saved.loc[1, "nces_district_id"])


def test_district_validate_input_missing_column():
    task = get_task("district_enrichment")
    df = pd.DataFrame([{"district_name": "Acme USD"}])  # missing state_abbr
    errors = task.validate_input(df)
    assert any("state_abbr" in e for e in errors)


def test_nces_validate_input_valid():
    task = get_task("nces_enrichment")
    df = pd.DataFrame([{"district_name": "Acme USD", "state_abbr": "CA"}])
    errors = task.validate_input(df)
    assert errors == []


# ---------------------------------------------------------------------------
# Column alias support
# ---------------------------------------------------------------------------


def test_district_validate_input_accepts_aliases():
    """validate_input() should accept 'district'/'state' column aliases."""
    task = get_task("district_enrichment")
    df = pd.DataFrame([{"district": "Acme USD", "state": "CA"}])
    assert task.validate_input(df) == []


def test_nces_validate_input_accepts_aliases():
    """validate_input() should accept 'district'/'state' column aliases."""
    task = get_task("nces_enrichment")
    df = pd.DataFrame([{"district": "Acme USD", "state": "CA"}])
    assert task.validate_input(df) == []


def test_district_build_jina_query_with_aliases():
    """build_jina_query() should work with aliased column names."""
    task = get_task("district_enrichment")
    row = pd.Series({"district": "Acme USD", "state": "CA"})
    query = task.build_jina_query(row)
    assert "Acme USD" in query
    assert "CA" in query


def test_nces_build_jina_query_with_aliases():
    """build_jina_query() should work with aliased column names."""
    task = get_task("nces_enrichment")
    row = pd.Series({"district": "Acme USD", "state": "CA"})
    query = task.build_jina_query(row)
    assert "Acme USD" in query
    assert "CA" in query


# ---------------------------------------------------------------------------
# NcesEnrichmentTask config
# ---------------------------------------------------------------------------


def test_nces_task_config_jina_max_results():
    """NcesEnrichmentTask should request only 2 Jina results by default."""
    task = get_task("nces_enrichment")
    assert task.config.jina_max_results == 2


def test_nces_task_config_default_model():
    """NcesEnrichmentTask should default to gpt-5-nano."""
    task = get_task("nces_enrichment")
    assert task.config.default_model == "gpt-5-nano"


def test_district_task_config_default_model():
    """DistrictEnrichmentTask should default to gpt-4o-mini."""
    task = get_task("district_enrichment")
    assert task.config.default_model == "gpt-4o-mini"
