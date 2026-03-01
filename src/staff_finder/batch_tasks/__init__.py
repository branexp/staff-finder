# Import tasks for registration side effects.
from . import district_enrichment as _district_enrichment  # noqa: F401
from .base import BatchTask, PreprocessResult
from .registry import get_task, list_tasks, register_task

__all__ = [
    "BatchTask",
    "PreprocessResult",
    "get_task",
    "list_tasks",
    "register_task",
]
