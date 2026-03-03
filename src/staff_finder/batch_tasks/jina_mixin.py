"""Mixin for batch tasks that require Jina web search."""

from __future__ import annotations

import json
import logging
import os
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import BatchTask, PreprocessResult, TaskConfig
from .errors import is_transient_http_error

logger = logging.getLogger(__name__)
JINA_FETCH_MAX_ATTEMPTS = 3


class JinaBatchTask(BatchTask):
    """Base class for batch tasks that use Jina web search during preprocessing."""

    requires_jina = True

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config)
        self._jina_client: Any = None

    @abstractmethod
    def build_jina_query(self, row: pd.Series) -> str:
        """Build a Jina search query for a single row. Return empty string to skip."""

    def build_jina_queries(self, row: pd.Series) -> list[str]:
        """Build a list of Jina search queries for a single row.

        Return an empty list to skip this row.
        Default implementation calls build_jina_query for single-query compatibility.
        """
        query = self.build_jina_query(row)
        return [query] if query else []

    @abstractmethod
    def format_jina_results(self, results: list[Any]) -> str:
        """Format Jina search results into a string for the LLM prompt."""

    def shortlist_candidates(
        self,
        per_query_results: list[list[Any]],
        limit: int,
    ) -> list[dict]:
        """Interleave candidates from multiple queries using round-robin.

        This prevents one query's results from dominating the shortlist.
        Returns a list of candidate dicts with url, title, content.
        """
        out: list[dict] = []
        seen_urls: set[str] = set()
        i = 0

        while len(out) < limit:
            added = False
            for results in per_query_results:
                if i < len(results):
                    result = results[i]
                    url_raw = (getattr(result, "url", "") or "").strip()
                    url_norm = url_raw.lower()
                    if url_norm and url_norm not in seen_urls:
                        out.append(
                            {
                                "title": (getattr(result, "title", None) or "").strip(),
                                "url": url_raw,
                                "content": (getattr(result, "content", None) or "").strip(),
                            }
                        )
                        seen_urls.add(url_norm)
                        if len(out) >= limit:
                            break
                    added = True
            if not added:
                break
            i += 1

        return out

    def _fetch_jina_results(
        self,
        query: str,
        *,
        num_results: int,
    ) -> list[Any]:
        """Fetch raw Jina search result objects for a single query with retry logic.

        Returns an empty list on any error so callers can continue gracefully.
        """
        if not query:
            return []

        @retry(
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(JINA_FETCH_MAX_ATTEMPTS),
            retry=retry_if_exception(is_transient_http_error),
        )
        def _fetch() -> list[Any]:
            client = self.get_jina_client()
            return client.search(query, num_results=num_results)

        try:
            return _fetch()
        except Exception:
            logger.warning(
                "Jina query failed after retries: query=%r attempts=%d",
                query,
                JINA_FETCH_MAX_ATTEMPTS,
                exc_info=True,
            )
            return []

    def fetch_row_content_multi_query(self, row: pd.Series) -> str:
        """Fetch and format Jina content for a row using multiple queries.

        Runs all queries from build_jina_queries(), shortlists results using
        round-robin deduplication, and formats for the LLM prompt.
        Each query uses the same tenacity retry logic as the single-query path.
        """
        queries = self.build_jina_queries(row)
        if not queries:
            return ""

        per_query_results: list[list[Any]] = [
            self._fetch_jina_results(q, num_results=self.config.jina_results_per_query)
            for q in queries
            if q
        ]

        # Shortlist candidates from all queries
        candidates = self.shortlist_candidates(
            per_query_results,
            limit=self.config.jina_max_results,
        )

        return self.format_jina_results(candidates)

    def get_jina_api_key(self) -> str:
        """Get Jina API key from environment."""
        key = os.getenv("STAFF_FINDER_JINA_API_KEY") or os.getenv("JINA_API_KEY")
        if not key:
            raise ValueError("Missing Jina API key. Set STAFF_FINDER_JINA_API_KEY or JINA_API_KEY.")
        return key

    def get_jina_client(self) -> Any:
        """Get a cached, authenticated Jina client instance."""
        if self._jina_client is None:
            try:
                from batchctl.core.clients.jina import JinaClient
            except ImportError as e:
                raise RuntimeError(
                    "batchctl is required for Jina preprocessing. "
                    "Install batchctl in the same Python environment as staff-finder."
                ) from e
            self._jina_client = JinaClient(api_key=self.get_jina_api_key())
        return self._jina_client

    def fetch_jina_content(
        self,
        query: str,
        *,
        num_results: int = 5,
    ) -> str:
        """Fetch and format Jina search results for a single query.

        Returns an empty string on any error so the LLM prompt stays clean.
        """
        results = self._fetch_jina_results(query, num_results=num_results)
        return self.format_jina_results(results) if results else ""

    def fetch_row_content(self, row: pd.Series) -> str:
        """Fetch Jina content for a single row.

        Override this to customize fetch behaviour (e.g. primary + fallback queries).
        The default implementation calls ``build_jina_query`` and ``fetch_jina_content``.
        """
        query = self.build_jina_query(row)
        return self.fetch_jina_content(query, num_results=self.config.jina_max_results)

    def preprocess_with_jina(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
        output_column: str = "web_content",
    ) -> PreprocessResult:
        """Generic preprocessing flow for Jina-based tasks."""
        df = pd.read_csv(input_csv, dtype=object)

        work_dir.mkdir(parents=True, exist_ok=True)
        processed_csv = work_dir / f"{input_csv.stem}_preprocessed.csv"

        # Build queries (stored for template reference)
        queries_series = df.apply(lambda row: self.build_jina_queries(row), axis=1)
        # JSON-encoded list for multi-query-aware templates (e.g. staff_directory.j2)
        df["jina_queries"] = queries_series.apply(json.dumps)
        # Backward-compatible single query column for existing templates (e.g. district_enrichment.j2)
        df["jina_query"] = queries_series.apply(lambda qs: qs[0] if qs else "")
        df[output_column] = ""

        worker_count = max(1, min(max_workers, 20))
        row_count = int(len(df))
        logger.info(
            "Starting Jina preprocessing: rows=%d workers=%d",
            row_count,
            worker_count,
        )

        # Choose fetch method based on multi-query setting
        fetch_func = (
            self.fetch_row_content_multi_query
            if self.config.jina_queries_per_row > 1
            else self.fetch_row_content
        )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(fetch_func, row): idx for idx, row in df.iterrows()}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    df.at[idx, output_column] = future.result()
                except Exception:
                    df.at[idx, output_column] = ""

        df.to_csv(processed_csv, index=False)
        success_count = int(df[output_column].fillna("").astype(str).str.len().gt(0).sum())
        failed_count = row_count - success_count
        logger.info(
            "Completed Jina preprocessing: rows=%d succeeded=%d failed=%d workers=%d",
            row_count,
            success_count,
            failed_count,
            worker_count,
        )
        return PreprocessResult(
            processed_csv=processed_csv,
            metadata={"row_count": row_count, "max_workers": worker_count},
        )
