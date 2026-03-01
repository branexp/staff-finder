from pathlib import Path

import pandas as pd

from staff_finder.batch_tasks import get_task, list_tasks


def test_district_enrichment_task_is_registered():
    assert "district_enrichment" in list_tasks()
    task = get_task("district_enrichment")
    assert task.__class__.__name__ == "DistrictEnrichmentTask"


def test_district_template_sections_load():
    task = get_task("district_enrichment")
    system_template, user_template = task.load_prompt_templates()
    assert "Return only valid JSON" in system_template
    assert "{{ record.web_content }}" in user_template


def test_district_postprocess_writes_expected_columns(tmp_path: Path):
    task = get_task("district_enrichment")
    original_df = pd.DataFrame(
        [
            {"district_name": "Acme Public Schools", "state_abbr": "TX"},
            {"district_name": "North Valley School District", "state_abbr": "CA"},
        ]
    )
    merged_df = pd.DataFrame(
        [
            {
                "source_index": 0,
                "status": "success",
                "output_content": (
                    '{"acronym":"APS","website_url":"https://www.acmeisd.org","domain":"acmeisd.org"}'
                ),
            },
            {
                "source_index": 1,
                "status": "success",
                "output_content": '{"acronym":"NVSD","website_url":null,"domain":"northvalley.k12.ca.us"}',
            },
        ]
    )

    output_csv = tmp_path / "district_enriched.csv"
    written = task.postprocess_data(merged_df, original_df, output_csv)
    assert written == output_csv

    saved = pd.read_csv(output_csv, dtype=object)
    assert saved.loc[0, "acronym"] == "APS"
    assert saved.loc[0, "website_url"] == "https://www.acmeisd.org"
    assert saved.loc[0, "domain"] == "acmeisd.org"
    assert saved.loc[1, "acronym"] == "NVSD"
    assert saved.loc[1, "website_url"] == "https://northvalley.k12.ca.us"
    assert saved.loc[1, "domain"] == "northvalley.k12.ca.us"
