"""Mixin for batch tasks that require Jina web search."""

from __future__ import annotations

import os
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import BatchTask, PreprocessResult
from .errors import is_transient_http_error


class JinaBatchTask(BatchTask):
    """Base class for batch tasks that use Jina web search during preprocessing."""

    requires_jina = True

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
        """Get an authenticated Jina client instance."""
        try:
            from batchctl.core.clients.jina import JinaClient
        except ImportError as e:
            raise RuntimeError(
                "batchctl is required for Jina preprocessing. "
                "Install batchctl in the same Python environment as staff-finder."
            ) from e

        return JinaClient(api_key=self.get_jina_api_key())

    def fetch_jina_content(
        self,
        query: str,
        *,
        num_results: int = 5,
        max_content_chars: int = 1500,
    ) -> str:
        """Fetch and format Jina search results for a single query."""
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
        except Exception as e:
            return f"ERROR: {e}"

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

        # Build queries
        df["jina_query"] = df.apply(self.build_jina_query, axis=1)
        df[output_column] = ""

        worker_count = max(1, min(max_workers, 20))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self.fetch_jina_content,
                    str(query),
                    num_results=self.config.jina_max_results,
                    max_content_chars=self.config.jina_max_content_chars,
                ): idx
                for idx, query in df["jina_query"].items()
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    df.at[idx, output_column] = future.result()
                except Exception as e:
                    df.at[idx, output_column] = f"ERROR: {e}"

        df.to_csv(processed_csv, index=False)
        return PreprocessResult(
            processed_csv=processed_csv,
            metadata={"row_count": int(len(df)), "max_workers": worker_count},
        )
