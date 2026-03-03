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


# ---------------------------------------------------------------------------
# StaffDirectoryTask
# ---------------------------------------------------------------------------


def test_staff_directory_task_is_registered():
    assert "staff_directory" in list_tasks()
    task = get_task("staff_directory")
    assert task.__class__.__name__ == "StaffDirectoryTask"


def test_staff_directory_task_registration():
    task = get_task("staff_directory")
    assert task is not None
    assert task.task_name == "staff_directory"


def test_staff_directory_builds_multiple_queries():
    task = get_task("staff_directory")
    row = pd.Series(
        {
            "school_name": "Lincoln Elementary",
            "district_name": "Springfield Public Schools",
            "city": "Springfield",
            "state_abbr": "IL",
        }
    )
    queries = task.build_jina_queries(row)
    assert len(queries) >= 2
    assert any("staff directory" in q.lower() for q in queries)


def test_staff_directory_builds_multiple_queries_without_district():
    task = get_task("staff_directory")
    row = pd.Series(
        {
            "school_name": "Lincoln Elementary",
            "state_abbr": "IL",
        }
    )
    queries = task.build_jina_queries(row)
    assert len(queries) >= 1
    assert any("Lincoln Elementary" in q for q in queries)


def test_staff_directory_empty_school_returns_no_queries():
    task = get_task("staff_directory")
    row = pd.Series({"school_name": "", "state_abbr": "IL"})
    queries = task.build_jina_queries(row)
    assert queries == []


def test_staff_directory_shortlisting():
    task = get_task("staff_directory")

    # Mock result objects using simple namespaces
    class _R:
        def __init__(self, url, title="", content=""):
            self.url = url
            self.title = title
            self.content = content

    per_query = [
        [_R("http://a.com", "A", "..."), _R("http://b.com", "B", "...")],
        [_R("http://c.com", "C", "..."), _R("http://a.com", "A dupe", "...")],  # dupe URL
    ]
    shortlisted = task.shortlist_candidates(per_query, limit=5)
    urls = [c["url"] for c in shortlisted]
    # Round-robin: a.com from query 0, c.com from query 1, b.com from query 0
    assert urls[0] == "http://a.com"
    assert urls[1] == "http://c.com"
    assert urls[2] == "http://b.com"
    assert urls.count("http://a.com") == 1  # No dupes


def test_staff_directory_shortlisting_respects_limit():
    task = get_task("staff_directory")

    class _R:
        def __init__(self, url):
            self.url = url
            self.title = ""
            self.content = ""

    per_query = [[_R(f"http://site{i}.com") for i in range(10)]]
    shortlisted = task.shortlist_candidates(per_query, limit=3)
    assert len(shortlisted) == 3


def test_staff_directory_template_sections_load():
    task = get_task("staff_directory")
    system_template, user_template = task.load_prompt_templates()
    assert "staff directory" in system_template.lower()
    assert "Return ONLY valid JSON" in system_template
    assert "{{ record." in user_template


def test_staff_directory_validate_input_accepts_aliases():
    task = get_task("staff_directory")
    df = pd.DataFrame([{"name": "Lincoln HS", "state": "IL"}])
    assert task.validate_input(df) == []


def test_staff_directory_validate_input_missing_school():
    task = get_task("staff_directory")
    df = pd.DataFrame([{"state_abbr": "IL"}])  # missing school column
    errors = task.validate_input(df)
    assert len(errors) >= 1


def test_staff_directory_validate_input_missing_state():
    task = get_task("staff_directory")
    df = pd.DataFrame([{"school_name": "Lincoln HS"}])  # missing state column
    errors = task.validate_input(df)
    assert len(errors) >= 1


def test_staff_directory_postprocess_writes_expected_columns(tmp_path: Path):
    task = get_task("staff_directory")
    original_df = pd.DataFrame(
        [
            {"school_name": "Lincoln Elementary", "state_abbr": "IL"},
            {"school_name": "Jefferson Middle School", "state_abbr": "CA"},
            {"school_name": "Unknown School", "state_abbr": "TX"},
        ]
    )
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": (
                    '{"staff_directory_url":"https://lincoln.il.edu/staff",'
                    '"confidence":"high","reasoning":"Official page"}'
                ),
            },
            {
                "source_index": 1,
                "status": "success",
                "output_content": (
                    '{"staff_directory_url":"https://jefferson.ca.edu/staff",'
                    '"confidence":"medium","reasoning":"District page"}'
                ),
            },
            {
                "source_index": 2,
                "status": "success",
                "output_content": '{"staff_directory_url":null,"confidence":"low","reasoning":"Not found"}',
            },
        ]
    )

    output_csv = tmp_path / "staff_directory_enriched.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)
    assert result.output_csv == output_csv
    assert result.rows_processed == 3
    assert result.rows_succeeded == 2
    assert result.rows_failed == 1

    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "staff_directory_url"] == "https://lincoln.il.edu/staff"
    assert saved.loc[0, "confidence"] == "high"
    assert saved.loc[1, "staff_directory_url"] == "https://jefferson.ca.edu/staff"
    assert saved.loc[1, "confidence"] == "medium"
    assert pd.isna(saved.loc[2, "staff_directory_url"])


def test_staff_directory_postprocess_not_found_sentinel(tmp_path: Path):
    task = get_task("staff_directory")
    original_df = pd.DataFrame([{"school_name": "Test School", "state_abbr": "TX"}])
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": '{"staff_directory_url":"NOT_FOUND","confidence":"low","reasoning":"none"}',
            }
        ]
    )

    output_csv = tmp_path / "not_found.csv"
    result = task.postprocess_data(merged_df, original_df, output_csv)
    assert result.rows_succeeded == 0
    assert result.rows_failed == 1

    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "staff_directory_url"] == "NOT_FOUND"


def test_staff_directory_task_config():
    task = get_task("staff_directory")
    assert task.config.default_model == "gpt-4o-mini"
    assert task.config.jina_queries_per_row == 4
    assert task.config.jina_max_results == 12
    assert task.config.max_workers == 10
