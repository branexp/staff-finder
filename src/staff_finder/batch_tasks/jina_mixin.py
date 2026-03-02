"""Mixin for batch tasks that require Jina web search."""

from __future__ import annotations

import os
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import BatchTask, PreprocessResult, TaskConfig
from .errors import is_transient_http_error


class JinaBatchTask(BatchTask):
    """Base class for batch tasks that use Jina web search during preprocessing."""

    requires_jina = True

    def __init__(self, config: TaskConfig | None = None) -> None:
        super().__init__(config)
        self._jina_client: Any = None

    @abstractmethod
    def build_jina_query(self, row: pd.Series) -> str:
        """Build a Jina search query for a single row. Return empty string to skip."""

    @abstractmethod
    def format_jina_results(self, results: list[Any]) -> str:
        """Format Jina search results into a string for the LLM prompt."""

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
        if not query:
            return ""

        @retry(
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            retry=retry_if_exception(is_transient_http_error),
        )
        def _fetch() -> str:
            client = self.get_jina_client()
            results = client.search(query, num_results=num_results)
            return self.format_jina_results(results)

        try:
            return _fetch()
        except Exception:
            return ""

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

        # Build primary queries (stored in the output CSV for template reference)
        df["jina_query"] = df.apply(self.build_jina_query, axis=1)
        df[output_column] = ""

        worker_count = max(1, min(max_workers, 20))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self.fetch_row_content, row): idx for idx, row in df.iterrows()
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    df.at[idx, output_column] = future.result()
                except Exception:
                    df.at[idx, output_column] = ""

        df.to_csv(processed_csv, index=False)
        return PreprocessResult(
            processed_csv=processed_csv,
            metadata={"row_count": int(len(df)), "max_workers": worker_count},
        )
