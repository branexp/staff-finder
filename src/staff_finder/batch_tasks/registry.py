from __future__ import annotations

from collections.abc import Callable

from .base import BatchTask

_TASK_REGISTRY: dict[str, type[BatchTask]] = {}


def register_task(name: str) -> Callable[[type[BatchTask]], type[BatchTask]]:
    """Register a batch task class under a unique task name."""

    def decorator(cls: type[BatchTask]) -> type[BatchTask]:
        if name in _TASK_REGISTRY:
            raise ValueError(f"Task {name!r} is already registered")
        _TASK_REGISTRY[name] = cls
        return cls

    return decorator


def get_task(name: str) -> BatchTask:
    """Instantiate a registered task by name."""
    task_cls = _TASK_REGISTRY.get(name)
    if task_cls is None:
        available = ", ".join(sorted(_TASK_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown task {name!r}. Available tasks: {available}")
    return task_cls()


def list_tasks() -> list[str]:
    """Return sorted names of all registered tasks."""
    return sorted(_TASK_REGISTRY)
