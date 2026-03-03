"""NCES District ID enrichment batch task."""

from __future__ import annotations

from pathlib import Path

import pandas as pd  # type: ignore

from .base import PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .dataframe_helpers import parse_json_response, require_column, resolve_value, validate_nces_id

# Canonical district/state column groups accepted as input
_DISTRICT_ALIASES = ("district_name", "district", "name")
_STATE_ALIASES = ("state_abbr", "state", "state_code")


@register_task("nces_enrichment")
class NcesEnrichmentTask(JinaBatchTask):
    """Enrich school districts with their 7-digit NCES District ID."""

    task_name = "nces_enrichment"
    description = "Find official 7-digit NCES District ID for school districts via Jina search."
    required_input_columns = ["district_name", "state_abbr"]
    output_columns = ["nces_district_id"]

    # NCES only needs 2 Jina results; use the task-specific lightweight model
    NCES_MODEL = "gpt-5-nano"

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(
            config
            or TaskConfig(
                default_model=self.NCES_MODEL,
                jina_max_results=2,
                max_workers=25,
            )
        )

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "nces_enrichment.j2"

    def validate_input(self, df: pd.DataFrame) -> list[str]:
        """Validate input, accepting common column name aliases."""
        errors: list[str] = []
        try:
            require_column(df, *_DISTRICT_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        try:
            require_column(df, *_STATE_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        return errors

    def build_jina_query(self, row: pd.Series) -> str:
        """Build primary query for NCES District ID."""
        district = resolve_value(row, *_DISTRICT_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)
        return f'"{district}" school district "{state}" "NCES District ID"'.strip()

    def build_fallback_query(self, row: pd.Series) -> str:
        """Build fallback query if primary returns no results."""
        district = resolve_value(row, *_DISTRICT_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)
        return (
            f'"{district}" "{state}" NCES ID site:nces.ed.gov OR site:publicschoolreview.com'
        ).strip()

    def format_jina_results(self, results: list) -> str:
        """Format up to jina_max_results results with content truncation."""
        chunks: list[str] = []
        for i, result in enumerate(results[: self.config.jina_max_results], 1):
            title = (getattr(result, "title", None) or "").strip()
            url = getattr(result, "url", "").strip()
            content = (getattr(result, "content", None) or "").strip()
            content = content[: self.config.jina_max_content_chars]
            chunks.append(f"[{i}] title: {title}\nurl: {url}\ncontent: {content}")
        return "\n\n".join(chunks)

    def fetch_row_content(self, row: pd.Series) -> str:
        """Try the primary query first; fall back to a secondary query when empty."""
        content = self.fetch_jina_content(
            self.build_jina_query(row), num_results=self.config.jina_max_results
        )
        if not content:
            content = self.fetch_jina_content(
                self.build_fallback_query(row), num_results=self.config.jina_max_results
            )
        return content

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
