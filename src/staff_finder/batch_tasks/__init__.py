"""Batch tasks for staff-finder."""

# Import tasks to trigger registration
from . import (
    district_enrichment,  # noqa: F401
    nces_enrichment,  # noqa: F401
)
from .base import BatchTask, PostprocessResult, PreprocessResult, TaskConfig
from .errors import (
    BatchTaskError,
    ErrorCode,
    NotFoundError,
    ProcessingError,
    TransientError,
    ValidationError,
)
from .registry import get_task, list_tasks, register_task
from .utils import (
    normalize_domain,
    parse_json_response,
    require_column,
    strip_json_fence,
    validate_nces_id,
)

__all__ = [
    # Base classes
    "BatchTask",
    "TaskConfig",
    "PreprocessResult",
    "PostprocessResult",
    # Errors
    "BatchTaskError",
    "ErrorCode",
    "NotFoundError",
    "ProcessingError",
    "TransientError",
    "ValidationError",
    # Registry
    "get_task",
    "list_tasks",
    "register_task",
    # Utilities
    "normalize_domain",
    "parse_json_response",
    "require_column",
    "strip_json_fence",
    "validate_nces_id",
]
