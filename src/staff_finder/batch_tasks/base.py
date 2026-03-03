"""Abstract base class for template-driven batch tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd  # type: ignore

from .errors import BatchTaskError  # noqa: F401

_SYSTEM_START = "{# SYSTEM_PROMPT_START #}"
_SYSTEM_END = "{# SYSTEM_PROMPT_END #}"
_USER_START = "{# USER_PROMPT_START #}"
_USER_END = "{# USER_PROMPT_END #}"


@dataclass
class TaskConfig:
    """Configuration options specific to a batch task."""

    # Override these in subclasses for task-specific defaults
    default_model: str = "gpt-4o-mini"
    max_workers: int = 5
    jina_max_results: int = 5
    jina_max_content_chars: int = 1500

    # Multi-query support
    jina_queries_per_row: int = 1  # Number of queries to run per input row
    jina_results_per_query: int = 5  # Results per individual query


@dataclass
class PreprocessResult:
    """Result container returned by task preprocessors."""

    processed_csv: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostprocessResult:
    """Result container returned by task postprocessors."""

    output_csv: Path
    rows_processed: int
    rows_succeeded: int
    rows_failed: int
    metadata: dict[str, Any] = field(default_factory=dict)


class BatchTask(ABC):
    """Abstract base class for template-driven batch tasks."""

    # Class-level metadata (override in subclasses)
    task_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires_jina: ClassVar[bool] = False
    required_input_columns: ClassVar[list[str]] = []
    output_columns: ClassVar[list[str]] = []

    def __init__(self, config: TaskConfig | None = None) -> None:
        self.config = config or TaskConfig()

    @abstractmethod
    def get_template_path(self) -> Path:
        """Return the absolute path to the task's prompt template file."""

    @abstractmethod
    def preprocess_data(
        self,
        input_csv: Path,
        work_dir: Path,
        *,
        max_workers: int,
    ) -> PreprocessResult:
        """Prepare input data for JSONL generation."""

    @abstractmethod
    def postprocess_data(
        self,
        merged_df: pd.DataFrame,
        original_df: pd.DataFrame,
        output_csv: Path,
    ) -> PostprocessResult:
        """Transform reconciled batch outputs and persist final enriched CSV."""

    def validate_input(self, df: pd.DataFrame) -> list[str]:
        """Validate input DataFrame. Returns list of validation errors."""
        errors: list[str] = []
        available = {c.lower() for c in df.columns}

        for col in self.required_input_columns:
            if col.lower() not in available:
                errors.append(f"Missing required column: {col}")

        return errors

    def load_prompt_templates(self) -> tuple[str, str]:
        """Load system/user prompt sections from this task's template file."""
        content = self.get_template_path().read_text(encoding="utf-8")

        system = self._extract_section(content, _SYSTEM_START, _SYSTEM_END, "system")
        user = self._extract_section(content, _USER_START, _USER_END, "user")
        return system, user

    @staticmethod
    def _extract_section(content: str, start: str, end: str, name: str) -> str:
        start_idx = content.find(start)
        end_idx = content.find(end)
        if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
            raise ValueError(
                f"Template is missing a valid {name!r} section delimited by "
                + f"{start!r} and {end!r}"
            )
        inner = content[start_idx + len(start) : end_idx].strip()
        if not inner:
            raise ValueError(f"Template {name!r} section is empty")
        return inner
