"""Staff directory URL discovery batch task."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd  # type: ignore

from .base import PostprocessResult, PreprocessResult, TaskConfig
from .jina_mixin import JinaBatchTask
from .registry import register_task
from .utils import parse_json_response, require_column, resolve_value

# Canonical column aliases for school input
_SCHOOL_ALIASES = ("school_name", "name", "school")
_DISTRICT_ALIASES = ("district_name", "district")
_CITY_ALIASES = ("city", "city_name")
_STATE_ALIASES = ("state_abbr", "state", "state_code")
_COUNTY_ALIASES = ("county_name", "county")


def _to_json_list(value: object) -> list:
    """Normalize a model field to a Python list, handling both list and JSON-string forms.

    LLMs sometimes return JSON arrays as pre-encoded strings; this prevents double-encoding.
    Returns an empty list when value is absent or cannot be parsed.
    """
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _build_query_variations(
    school: str,
    district: str,
    city: str,
    state: str,
    max_queries: int,
) -> list[str]:
    """Build multiple query variations for staff directory discovery.

    Ordered by expected signal quality.
    """
    where = " ".join([p for p in (city, state) if p])
    q_school = f'"{school}"' if school else ""
    q_district = f'"{district}"' if district else ""

    candidates = [
        f'{q_school} "staff directory" {where}'.strip(),
        f'{q_school} ("faculty & staff" OR "faculty and staff" OR "staff") {where}'.strip(),
        f'{q_school} ("our staff" OR "staff list" OR "faculty directory" OR "directory") {where}'.strip(),
    ]

    if district:
        candidates.append(
            f'{q_district} ("staff directory" OR "directory") {q_school} {where}'.strip()
        )

    # Dedupe and clean
    seen, out = set(), []
    for q in candidates:
        q = re.sub(r"\s+", " ", q).strip()
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
        if len(out) >= max_queries:
            break

    return out


@register_task("staff_directory")
class StaffDirectoryTask(JinaBatchTask):
    """Discover staff directory URLs for schools."""

    task_name = "staff_directory"
    description = "Find staff directory URLs for K-12 schools via multi-query Jina search."
    required_input_columns = ["school_name", "state_abbr"]
    output_columns = [
        "staff_directory_url",
        "confidence",
        "reasoning",
        # Optional additional columns
        "candidate_urls",
        "queries_used",
    ]

    # Stage 1 (active): Candidate evaluation and selection
    STAGE_1_MODEL = "gpt-4o-mini"
    # Stage 2 (optional, for high-value runs): URL validation
    STAGE_2_MODEL = "gpt-4o-mini"

    def __init__(self, config: TaskConfig | None = None) -> None:
        cfg = config or TaskConfig(
            default_model=self.STAGE_1_MODEL,
            max_workers=10,
            jina_max_results=12,  # Final candidates for LLM
            jina_queries_per_row=4,  # Query variations per school
            jina_results_per_query=5,  # Results per query before shortlist
        )
        super().__init__(cfg)

    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "staff_directory.j2"

    def get_stage2_template_path(self) -> Path:
        """Return the path to the optional stage 2 validation template.

        Stage 2 is an optional validation pass for high-value runs.
        It is not invoked automatically; callers may use it to verify
        selected URLs before writing final output.
        """
        return Path(__file__).resolve().parent.parent / "templates" / "staff_directory_stage2.j2"

    def validate_input(self, df: pd.DataFrame) -> list[str]:
        """Validate input, accepting common column name aliases."""
        errors: list[str] = []
        try:
            require_column(df, *_SCHOOL_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        try:
            require_column(df, *_STATE_ALIASES)
        except ValueError as e:
            errors.append(str(e))
        return errors

    def build_jina_query(self, row: pd.Series) -> str:
        """Build a single Jina search query (used as fallback for single-query mode)."""
        school = resolve_value(row, *_SCHOOL_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)
        q_school = f'"{school}"' if school else ""
        return f'{q_school} "staff directory" {state}'.strip()

    def build_jina_queries(self, row: pd.Series) -> list[str]:
        """Build multiple query variations for staff directory discovery."""
        school = resolve_value(row, *_SCHOOL_ALIASES)
        district = resolve_value(row, *_DISTRICT_ALIASES)
        city = resolve_value(row, *_CITY_ALIASES)
        state = resolve_value(row, *_STATE_ALIASES)

        if not school:
            return []

        return _build_query_variations(
            school=school,
            district=district,
            city=city,
            state=state,
            max_queries=self.config.jina_queries_per_row,
        )

    def format_jina_results(self, results: list) -> str:
        """Format shortlisted candidates for the LLM prompt.

        Expects a list of dicts (from shortlist_candidates), not raw Jina results.
        """
        chunks: list[str] = []
        for i, candidate in enumerate(results, 1):
            title = (candidate.get("title", "") or "").strip()
            url = (candidate.get("url", "") or "").strip()
            content = (candidate.get("content", "") or "").strip()
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
            output_column="candidates",
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        enriched = original_df.copy()

        # Ensure all output columns exist
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

            # Extract main fields
            url = payload.get("staff_directory_url") or payload.get("selected_url")
            confidence = payload.get("confidence")
            reasoning = payload.get("reasoning", "")

            # Handle NOT_FOUND vs null
            if url and url.lower() in ("not_found", "null", "none", ""):
                url = "NOT_FOUND"

            # Extract optional fields, normalizing to list regardless of model output type
            candidate_urls = _to_json_list(payload.get("candidate_urls"))
            queries_used = _to_json_list(payload.get("queries_used"))

            # Write to enriched
            if url:
                enriched.at[source_index, "staff_directory_url"] = str(url).strip()
            if confidence:
                enriched.at[source_index, "confidence"] = str(confidence).strip()
            if reasoning:
                enriched.at[source_index, "reasoning"] = str(reasoning).strip()
            if candidate_urls:
                enriched.at[source_index, "candidate_urls"] = json.dumps(candidate_urls)
            if queries_used:
                enriched.at[source_index, "queries_used"] = json.dumps(queries_used)
            if url and url != "NOT_FOUND":
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
