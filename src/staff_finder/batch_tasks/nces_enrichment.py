"""NCES District ID enrichment batch task."""

from __future__ import annotations

from pathlib import Path

import pandas as pd  # type: ignore

from .base import PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import parse_json_response, validate_nces_id


@register_task("nces_enrichment")
class NcesEnrichmentTask(JinaBatchTask):
    """Enrich school districts with their 7-digit NCES District ID."""

    task_name = "nces_enrichment"
    description = "Find official 7-digit NCES District ID for school districts via Jina search."
    required_input_columns = ["district_name", "state_abbr"]
    output_columns = ["nces_district_id"]

    # NCES-specific config
    NCES_MODEL = "gpt-5-nano"

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config or TaskConfig(default_model=self.NCES_MODEL))

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "nces_enrichment.j2"

    def build_jina_query(self, row: pd.Series) -> str:
        """Build primary query for NCES District ID."""
        district = (
            "" if pd.isna(row.get("district_name")) else str(row.get("district_name")).strip()
        )
        state = "" if pd.isna(row.get("state_abbr")) else str(row.get("state_abbr")).strip()
        return f'"{district}" school district "{state}" "NCES District ID"'.strip()

    def build_fallback_query(self, row: pd.Series) -> str:
        """Build fallback query if primary returns no results."""
        district = (
            "" if pd.isna(row.get("district_name")) else str(row.get("district_name")).strip()
        )
        state = "" if pd.isna(row.get("state_abbr")) else str(row.get("state_abbr")).strip()
        return (
            f'"{district}" "{state}" NCES ID site:nces.ed.gov OR site:publicschoolreview.com'
        ).strip()

    def format_jina_results(self, results: list) -> str:
        """Format results with NCES-specific truncation."""
        chunks: list[str] = []
        for i, result in enumerate(results[:2], 1):  # NCES only needs 2 results
            title = (getattr(result, "title", None) or "").strip()
            url = getattr(result, "url", "").strip()
            content = (getattr(result, "content", None) or "").strip()
            content = content[: self.config.jina_max_content_chars]
            chunks.append(f"[{i}] title: {title}\nurl: {url}\ncontent: {content}")
        return "\n\n".join(chunks)

    def preprocess_data(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
    ) -> PreprocessResult:
        df = pd.read_csv(input_csv, dtype=object)

        # Validate input
        errors = self.validate_input(df)
        if errors:
            raise ValueError("; ".join(errors))

        return self.preprocess_with_jina(
            input_csv,
            work_dir,
            max_workers=max_workers,
            output_column="web_content",
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        enriched = original_df.copy()
        if "nces_district_id" not in enriched.columns:
            enriched["nces_district_id"] = pd.NA

        status_col = "status" if "status" in merged_df.columns else None
        rows_succeeded = 0
        rows_failed = 0

        for _, row in merged_df.iterrows():
            try:
                source_index = int(row.get("source_index"))
            except Exception:
                rows_failed += 1
                continue

            if source_index < 0 or source_index >= len(enriched):
                rows_failed += 1
                continue

            if status_col and str(row.get(status_col, "")).lower() != "success":
                rows_failed += 1
                continue

            raw = row.get("output_content")
            payload = parse_json_response(raw)
            if payload is None:
                rows_failed += 1
                continue

            nces_id = validate_nces_id(payload.get("nces_district_id"))
            if nces_id:
                enriched.at[source_index, "nces_district_id"] = nces_id
                rows_succeeded += 1
            else:
                rows_failed += 1

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_csv(output_csv, index=False)

        return PostprocessResult(
            output_csv=output_csv,
            rows_processed=len(enriched),
            rows_succeeded=rows_succeeded,
            rows_failed=rows_failed,
        )
