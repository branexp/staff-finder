"""Configuration management for Staff Finder."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

# Load .env once on import (does nothing if file absent)
load_dotenv(override=False)

_logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Get integer from environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        _logger.warning("Invalid value for %s: '%s', using default %d", name, val, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Get float from environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        _logger.warning("Invalid value for %s: '%s', using default %s", name, val, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Get boolean from environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    val_lower = val.lower()
    if val_lower in ("true", "1", "yes", "on"):
        return True
    if val_lower in ("false", "0", "no", "off"):
        return False
    _logger.warning("Invalid boolean value for %s: '%s', using default %s", name, val, default)
    return default


def _env_str(name: str, default: str) -> str:
    """Get string from environment variable."""
    return os.getenv(name, default)


@dataclass
class Settings:
    """Configuration settings for Staff Finder."""
    
    # IO
    input_csv: str = field(default_factory=lambda: _env_str("INPUT_CSV", "schools.csv"))
    output_csv: str = field(
        default_factory=lambda: _env_str("OUTPUT_CSV", "schools_with_staff_links.csv")
    )
    system_prompt_path: str = field(
        default_factory=lambda: _env_str("SYSTEM_PROMPT_PATH", "system_prompt.md")
    )

    # OpenAI
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env_str("OPENAI_MODEL", "gpt-5-mini"))
    openai_verbosity: str = field(default_factory=lambda: _env_str("OPENAI_VERBOSITY", "low"))
    openai_reasoning_effort: str = field(
        default_factory=lambda: _env_str("OPENAI_REASONING_EFFORT", "low")
    )
    openai_request_timeout: float = field(
        default_factory=lambda: _env_float("OPENAI_REQUEST_TIMEOUT", 30.0)
    )

    # Jina
    jina_api_key: str | None = field(default_factory=lambda: os.getenv("JINA_API_KEY"))
    jina_base_url: str = field(
        default_factory=lambda: _env_str("JINA_BASE_URL", "https://s.jina.ai").rstrip("/")
    )
    jina_no_cache: bool = field(default_factory=lambda: _env_bool("JINA_NO_CACHE", False))
    jina_request_timeout: float = field(
        default_factory=lambda: _env_float("JINA_REQUEST_TIMEOUT", 30.0)
    )

    # Planner / shortlist
    max_queries_per_school: int = field(
        default_factory=lambda: _env_int("MAX_QUERIES_PER_SCHOOL", 3)
    )
    candidates_for_selection: int = field(
        default_factory=lambda: _env_int("CANDIDATES_FOR_SELECTION", 10)
    )

    # Concurrency
    max_concurrent_schools: int = field(
        default_factory=lambda: _env_int("MAX_CONCURRENT_SCHOOLS", 5)
    )
    max_concurrent_jina: int = field(default_factory=lambda: _env_int("MAX_CONCURRENT_JINA", 10))
    max_concurrent_openai: int = field(
        default_factory=lambda: _env_int("MAX_CONCURRENT_OPENAI", 4)
    )

    # Pacing & checkpoint
    per_row_delay_sec: float = field(default_factory=lambda: _env_float("PER_ROW_DELAY_SEC", 0.0))
    checkpoint_every: int = field(default_factory=lambda: _env_int("CHECKPOINT_EVERY", 250))
    enable_resume: bool = field(default_factory=lambda: _env_bool("ENABLE_RESUME", True))

    # Cache
    enable_jina_cache: bool = field(default_factory=lambda: _env_bool("ENABLE_JINA_CACHE", True))
    cache_dir: Path = field(default_factory=lambda: Path(_env_str("CACHE_DIR", ".cache_jina")))

    # Retry settings
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    retry_initial_wait: float = field(default_factory=lambda: _env_float("RETRY_INITIAL_WAIT", 1.0))
    retry_max_wait: float = field(default_factory=lambda: _env_float("RETRY_MAX_WAIT", 8.0))

    # Content truncation
    max_content_chars: int = field(default_factory=lambda: _env_int("MAX_CONTENT_CHARS", 500))

    # Logging
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO"))


def require_keys(cfg: Settings) -> None:
    """Validate required settings."""
    if not cfg.jina_api_key:
        raise RuntimeError("JINA_API_KEY environment variable is required.")
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required.")
    
    # Warnings for edge-case values
    if cfg.max_concurrent_openai > 10:
        _logger.warning(
            "MAX_CONCURRENT_OPENAI=%d may exceed rate limits",
            cfg.max_concurrent_openai,
        )
    if cfg.checkpoint_every < 10:
        _logger.warning(
            "CHECKPOINT_EVERY=%d may cause excessive disk writes",
            cfg.checkpoint_every,
        )
    if cfg.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        _logger.warning("Invalid LOG_LEVEL '%s', defaulting to INFO", cfg.log_level)
        cfg.log_level = "INFO"
    if cfg.openai_verbosity.lower() not in ("low", "medium", "high"):
        _logger.warning("Invalid OPENAI_VERBOSITY '%s', defaulting to low", cfg.openai_verbosity)
        cfg.openai_verbosity = "low"
    if cfg.openai_reasoning_effort.lower() not in ("low", "medium", "high"):
        _logger.warning(
            "Invalid OPENAI_REASONING_EFFORT '%s', defaulting to low",
            cfg.openai_reasoning_effort,
        )
        cfg.openai_reasoning_effort = "low"
