"""Batch tasks for staff-finder."""

# Import tasks to trigger registration
from . import (
    district_enrichment,  # noqa: F401
    nces_enrichment,  # noqa: F401
    staff_directory,  # noqa: F401
)
from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .errors import BatchTaskError
from .jina_mixin import JinaBatchTask
from .registry import get_task, list_tasks, register_task

__all__ = [
    "BatchTask",
    "JinaBatchTask",
    "TaskConfig",
    "PreprocessResult",
    "PostprocessResult",
    "BatchTaskError",
    "get_task",
    "list_tasks",
    "register_task",
]
