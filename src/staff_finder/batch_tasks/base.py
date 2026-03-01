from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore

_SYSTEM_START = "{# SYSTEM_PROMPT_START #}"
_SYSTEM_END = "{# SYSTEM_PROMPT_END #}"
_USER_START = "{# USER_PROMPT_START #}"
_USER_END = "{# USER_PROMPT_END #}"


@dataclass
class PreprocessResult:
    """Result container returned by task preprocessors."""

    processed_csv: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class BatchTask(ABC):
    """Abstract base class for template-driven batch tasks."""

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
    ) -> Path:
        """Transform reconciled batch outputs and persist final enriched CSV."""

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
