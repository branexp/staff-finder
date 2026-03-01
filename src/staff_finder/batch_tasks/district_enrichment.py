from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd  # type: ignore

from .base import BatchTask, PreprocessResult
from .registry import register_task


def _require_column(df: pd.DataFrame, *aliases: str) -> str:
    lower = {c.lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    raise ValueError(
        f"Missing required column. Expected one of: {', '.join(aliases)}. "
        + f"Found: {', '.join(df.columns)}"
    )


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


@register_task("district_enrichment")
class DistrictEnrichmentTask(BatchTask):
    def get_template_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "templates" / "district_enrichment.j2"

    def preprocess_data(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
    ) -> PreprocessResult:
        try:
            from batchctl.core.clients.jina import JinaClient
        except Exception as e:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "batchctl is required for district_enrichment preprocessing. "
                + "Install batchctl in the same Python environment as staff-finder."
            ) from e

        api_key = os.getenv("STAFF_FINDER_JINA_API_KEY") or os.getenv("JINA_API_KEY")
        if not api_key:
            raise ValueError("Missing Jina API key. Set STAFF_FINDER_JINA_API_KEY or JINA_API_KEY.")

        df = pd.read_csv(input_csv, dtype=object)
        district_col = _require_column(df, "district_name", "district", "name")
        state_col = _require_column(df, "state_abbr", "state", "state_code")

        work_dir.mkdir(parents=True, exist_ok=True)
        processed_csv = work_dir / f"{input_csv.stem}_district_preprocessed.csv"

        def build_query(row: pd.Series) -> str:
            district = "" if pd.isna(row[district_col]) else str(row[district_col]).strip()
            state = "" if pd.isna(row[state_col]) else str(row[state_col]).strip()
            return f"{district} {state} public schools official website acronym".strip()

        df["jina_query"] = df.apply(build_query, axis=1)
        df["web_content"] = ""

        client = JinaClient(api_key=api_key)
        worker_count = max(1, min(max_workers, 20))

        def fetch(query: str) -> str:
            if not query:
                return ""
            results = client.search(query, num_results=5)
            chunks: list[str] = []
            for i, result in enumerate(results, 1):
                title = (result.title or "").strip()
                description = (result.description or "").strip()
                content = (result.content or "").strip()
                url = result.url.strip()
                chunks.append(
                    f"[{i}] title: {title}\nurl: {url}\ndescription: {description}\ncontent: {content}"
                )
            return "\n\n".join(chunks)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(fetch, str(query)): idx for idx, query in df["jina_query"].items()
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    df.at[idx, "web_content"] = future.result()
                except Exception as e:
                    df.at[idx, "web_content"] = f"ERROR: {e}"

        df.to_csv(processed_csv, index=False)
        return PreprocessResult(
            processed_csv=processed_csv,
            metadata={"row_count": int(len(df)), "max_workers": worker_count},
        )

    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> Path:
        enriched = original_df.copy()
        for col in ("acronym", "website_url", "domain"):
            if col not in enriched.columns:
                enriched[col] = pd.NA

        status_col = "status" if "status" in merged_df.columns else None
        for _, row in merged_df.iterrows():
            try:
                source_index = int(row.get("source_index"))
            except Exception:
                continue
            if source_index < 0 or source_index >= len(enriched):
                continue
            if status_col and str(row.get(status_col, "")).lower() != "success":
                continue

            raw = row.get("output_content")
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            content = _strip_json_fence(str(raw))
            try:
                payload = json.loads(content)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue

            acronym = payload.get("acronym")
            website_url = payload.get("website_url")
            domain = payload.get("domain")

            if website_url and not isinstance(website_url, str):
                website_url = str(website_url)
            if domain and not isinstance(domain, str):
                domain = str(domain)
            # Always normalize domain from either the explicit field or the website URL.
            domain = _normalize_domain(domain) or _normalize_domain(website_url)
            if not website_url and domain:
                website_url = f"https://{domain}"
            elif website_url and "://" not in website_url:
                website_url = f"https://{website_url}"

            if acronym:
                enriched.at[source_index, "acronym"] = str(acronym).strip()
            if website_url:
                enriched.at[source_index, "website_url"] = str(website_url).strip()
            if domain:
                enriched.at[source_index, "domain"] = str(domain).strip()

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_csv(output_csv, index=False)
        return output_csv
