"""District enrichment batch task."""

from __future__ import annotations

from pathlib import Path

import pandas as pd  # type: ignore

from .base import PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import normalize_domain, parse_json_response, require_column, resolve_value

# Canonical district/state column groups accepted as input
_DISTRICT_ALIASES = ("district_name", "district", "name")
_STATE_ALIASES = ("state_abbr", "state", "state_code")


@register_task("district_enrichment")
class DistrictEnrichmentTask(JinaBatchTask):
    """Enrich school districts with website URL and acronym."""

    task_name = "district_enrichment"
    description = "Enrich school districts with official website URL and acronym via Jina search."
    required_input_columns = ["district_name", "state_abbr"]
    output_columns = ["acronym", "website_url", "domain"]

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config or TaskConfig(default_model="gpt-4o-mini"))

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "district_enrichment.j2"

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
        district = resolve_value(row, *_DISTRICT_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)
        district_part = f'"{district}"' if district else ""
        return f"{district_part} {state} school district official website".strip()

    def format_jina_results(self, results: list) -> str:
        chunks: list[str] = []
        for i, result in enumerate(results, 1):
            title = (getattr(result, "title", None) or "").strip()
            description = (getattr(result, "description", None) or "").strip()
            content = (getattr(result, "content", None) or "").strip()
            content = content[: self.config.jina_max_content_chars]
            url = getattr(result, "url", "").strip()
            chunks.append(
                f"[{i}] title: {title}\nurl: {url}\ndescription: {description}\ncontent: {content}"
            )
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
        for col in self.output_columns:
            if col not in enriched.columns:
                enriched[col] = pd.NA

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

            acronym = payload.get("acronym")
            website_url = payload.get("website_url")

            if website_url and not isinstance(website_url, str):
                website_url = str(website_url)

            if website_url and "://" not in website_url:
                website_url = f"https://{website_url}"

            domain = normalize_domain(website_url)

            if acronym:
                enriched.at[source_index, "acronym"] = str(acronym).strip()
            if website_url:
                enriched.at[source_index, "website_url"] = str(website_url).strip()
            if domain:
                enriched.at[source_index, "domain"] = str(domain).strip()

            if acronym or website_url or domain:
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
