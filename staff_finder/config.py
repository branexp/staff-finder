from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass
from typing import Any

from platformdirs import user_config_dir


@dataclass
class Settings:
    # IO
    input_csv: str = "schools.csv"
    output_csv: str = "schools_with_staff_links.csv"
    system_prompt_path: str = "system_prompt.md"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_verbosity: str = "low"
    openai_reasoning_effort: str = "low"
    openai_request_timeout: float = 30.0

    # Jina
    jina_api_key: str | None = None
    jina_base_url: str = "https://s.jina.ai"
    jina_no_cache: bool = False
    jina_request_timeout: float = 30.0

    # Planner / shortlist
    max_queries_per_school: int = 3
    candidates_for_selection: int = 10

    # Concurrency
    max_concurrent_schools: int = 5
    max_concurrent_jina: int = 10
    max_concurrent_openai: int = 4

    # Pacing & checkpoint
    per_row_delay_sec: float = 0.0
    checkpoint_every: int = 250
    enable_resume: bool = True

    # Cache
    enable_jina_cache: bool = True
    cache_dir: pathlib.Path = pathlib.Path(".cache_jina")

    # Retry settings
    max_retries: int = 3
    retry_initial_wait: float = 1.0
    retry_max_wait: float = 8.0

    # Content truncation
    max_content_chars: int = 500

    # Logging
    log_level: str = "INFO"


class ConfigError(RuntimeError):
    pass


def _load_toml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        raise ConfigError(f"Failed to parse config TOML: {path}: {e}") from e
    if not isinstance(data, dict):
        return {}
    return data


def default_config_paths() -> list[pathlib.Path]:
    # Precedence (lower → higher): XDG config then legacy homefile
    xdg = pathlib.Path(user_config_dir("staff-finder")) / "config.toml"
    legacy = pathlib.Path.home() / ".staff-finder.toml"
    return [xdg, legacy]


def _env(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v if v != "" else None


def load_settings(
    *,
    # Special: override which config file(s) to load
    config_path: pathlib.Path | None = None,
    # IO
    input_csv: str | None = None,
    output_csv: str | None = None,
    system_prompt_path: str | None = None,
    # OpenAI
    openai_api_key: str | None = None,
    openai_model: str | None = None,
    openai_verbosity: str | None = None,
    openai_reasoning_effort: str | None = None,
    openai_request_timeout: float | None = None,
    # Jina
    jina_api_key: str | None = None,
    jina_base_url: str | None = None,
    jina_no_cache: bool | None = None,
    jina_request_timeout: float | None = None,
    # Planner / shortlist
    max_queries_per_school: int | None = None,
    candidates_for_selection: int | None = None,
    # Concurrency
    max_concurrent_schools: int | None = None,
    max_concurrent_jina: int | None = None,
    max_concurrent_openai: int | None = None,
    # Pacing & checkpoint
    per_row_delay_sec: float | None = None,
    checkpoint_every: int | None = None,
    enable_resume: bool | None = None,
    # Cache
    enable_jina_cache: bool | None = None,
    cache_dir: str | pathlib.Path | None = None,
    # Retry settings
    max_retries: int | None = None,
    retry_initial_wait: float | None = None,
    retry_max_wait: float | None = None,
    # Content truncation
    max_content_chars: int | None = None,
    # Logging
    log_level: str | None = None,
) -> Settings:
    """Load settings using precedence:

    1) explicit args (CLI flags)
    2) env vars
    3) config TOML
    4) defaults

    Env vars (preferred):
      STAFF_FINDER_OPENAI_API_KEY, STAFF_FINDER_JINA_API_KEY, ...

    Back-compat env vars (also supported):
      OPENAI_API_KEY, JINA_API_KEY, OPENAI_MODEL, ...
    """

    file_cfg: dict[str, Any] = {}
    if config_path is not None:
        file_cfg.update(_load_toml(pathlib.Path(config_path)))
    else:
        for p in default_config_paths():
            file_cfg.update(_load_toml(p))

    env_cfg: dict[str, Any] = {
        # IO
        "input_csv": _env("STAFF_FINDER_INPUT_CSV") or _env("INPUT_CSV"),
        "output_csv": _env("STAFF_FINDER_OUTPUT_CSV") or _env("OUTPUT_CSV"),
        "system_prompt_path": _env("STAFF_FINDER_SYSTEM_PROMPT_PATH") or _env("SYSTEM_PROMPT_PATH"),
        # OpenAI
        "openai_api_key": _env("STAFF_FINDER_OPENAI_API_KEY") or _env("OPENAI_API_KEY"),
        "openai_model": _env("STAFF_FINDER_OPENAI_MODEL") or _env("OPENAI_MODEL"),
        "openai_verbosity": _env("STAFF_FINDER_OPENAI_VERBOSITY") or _env("OPENAI_VERBOSITY"),
        "openai_reasoning_effort": _env("STAFF_FINDER_OPENAI_REASONING_EFFORT")
        or _env("OPENAI_REASONING_EFFORT"),
        "openai_request_timeout": _env("STAFF_FINDER_OPENAI_REQUEST_TIMEOUT")
        or _env("OPENAI_REQUEST_TIMEOUT"),
        # Jina
        "jina_api_key": _env("STAFF_FINDER_JINA_API_KEY") or _env("JINA_API_KEY"),
        "jina_base_url": _env("STAFF_FINDER_JINA_BASE_URL") or _env("JINA_BASE_URL"),
        "jina_no_cache": _env("STAFF_FINDER_JINA_NO_CACHE") or _env("JINA_NO_CACHE"),
        "jina_request_timeout": _env("STAFF_FINDER_JINA_REQUEST_TIMEOUT")
        or _env("JINA_REQUEST_TIMEOUT"),
        # Planner / shortlist
        "max_queries_per_school": _env("STAFF_FINDER_MAX_QUERIES_PER_SCHOOL")
        or _env("MAX_QUERIES_PER_SCHOOL"),
        "candidates_for_selection": _env("STAFF_FINDER_CANDIDATES_FOR_SELECTION")
        or _env("CANDIDATES_FOR_SELECTION"),
        # Concurrency
        "max_concurrent_schools": _env("STAFF_FINDER_MAX_CONCURRENT_SCHOOLS")
        or _env("MAX_CONCURRENT_SCHOOLS"),
        "max_concurrent_jina": _env("STAFF_FINDER_MAX_CONCURRENT_JINA")
        or _env("MAX_CONCURRENT_JINA"),
        "max_concurrent_openai": _env("STAFF_FINDER_MAX_CONCURRENT_OPENAI")
        or _env("MAX_CONCURRENT_OPENAI"),
        # Pacing & checkpoint
        "per_row_delay_sec": _env("STAFF_FINDER_PER_ROW_DELAY_SEC") or _env("PER_ROW_DELAY_SEC"),
        "checkpoint_every": _env("STAFF_FINDER_CHECKPOINT_EVERY") or _env("CHECKPOINT_EVERY"),
        "enable_resume": _env("STAFF_FINDER_ENABLE_RESUME") or _env("ENABLE_RESUME"),
        # Cache
        "enable_jina_cache": _env("STAFF_FINDER_ENABLE_JINA_CACHE") or _env("ENABLE_JINA_CACHE"),
        "cache_dir": _env("STAFF_FINDER_CACHE_DIR") or _env("CACHE_DIR"),
        # Retry settings
        "max_retries": _env("STAFF_FINDER_MAX_RETRIES") or _env("MAX_RETRIES"),
        "retry_initial_wait": _env("STAFF_FINDER_RETRY_INITIAL_WAIT") or _env("RETRY_INITIAL_WAIT"),
        "retry_max_wait": _env("STAFF_FINDER_RETRY_MAX_WAIT") or _env("RETRY_MAX_WAIT"),
        # Content truncation
        "max_content_chars": _env("STAFF_FINDER_MAX_CONTENT_CHARS") or _env("MAX_CONTENT_CHARS"),
        # Logging
        "log_level": _env("STAFF_FINDER_LOG_LEVEL") or _env("LOG_LEVEL"),
    }

    def pick(key: str, explicit_value: Any) -> Any:
        if explicit_value is not None:
            return explicit_value
        if env_cfg.get(key) not in (None, ""):
            return env_cfg[key]
        if key in file_cfg and file_cfg[key] not in (None, ""):
            return file_cfg[key]
        return None

    def to_int(key: str, v: Any, default: int) -> int:
        if v is None:
            return default
        try:
            return int(v)
        except Exception as e:
            raise ConfigError(f"{key} must be an integer") from e

    def to_float(key: str, v: Any, default: float) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except Exception as e:
            raise ConfigError(f"{key} must be a number") from e

    def to_bool(key: str, v: Any, default: bool) -> bool:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ConfigError(f"{key} must be a boolean (true/false)")

    def to_path(key: str, v: Any, default: pathlib.Path) -> pathlib.Path:
        if v is None:
            return default
        try:
            return pathlib.Path(str(v))
        except Exception as e:
            raise ConfigError(f"{key} must be a path") from e

    cfg = Settings(
        input_csv=str(pick("input_csv", input_csv) or Settings.input_csv),
        output_csv=str(pick("output_csv", output_csv) or Settings.output_csv),
        system_prompt_path=str(
            pick("system_prompt_path", system_prompt_path) or Settings.system_prompt_path
        ),
        openai_api_key=pick("openai_api_key", openai_api_key),
        openai_model=str(pick("openai_model", openai_model) or Settings.openai_model),
        openai_verbosity=str(
            pick("openai_verbosity", openai_verbosity) or Settings.openai_verbosity
        ),
        openai_reasoning_effort=str(
            pick("openai_reasoning_effort", openai_reasoning_effort)
            or Settings.openai_reasoning_effort
        ),
        openai_request_timeout=to_float(
            "openai_request_timeout",
            pick("openai_request_timeout", openai_request_timeout),
            Settings.openai_request_timeout,
        ),
        jina_api_key=pick("jina_api_key", jina_api_key),
        jina_base_url=str(
            pick("jina_base_url", jina_base_url) or Settings.jina_base_url
        ).rstrip("/"),
        jina_no_cache=to_bool(
            "jina_no_cache", pick("jina_no_cache", jina_no_cache), Settings.jina_no_cache
        ),
        jina_request_timeout=to_float(
            "jina_request_timeout",
            pick("jina_request_timeout", jina_request_timeout),
            Settings.jina_request_timeout,
        ),
        max_queries_per_school=to_int(
            "max_queries_per_school",
            pick("max_queries_per_school", max_queries_per_school),
            Settings.max_queries_per_school,
        ),
        candidates_for_selection=to_int(
            "candidates_for_selection",
            pick("candidates_for_selection", candidates_for_selection),
            Settings.candidates_for_selection,
        ),
        max_concurrent_schools=to_int(
            "max_concurrent_schools",
            pick("max_concurrent_schools", max_concurrent_schools),
            Settings.max_concurrent_schools,
        ),
        max_concurrent_jina=to_int(
            "max_concurrent_jina",
            pick("max_concurrent_jina", max_concurrent_jina),
            Settings.max_concurrent_jina,
        ),
        max_concurrent_openai=to_int(
            "max_concurrent_openai",
            pick("max_concurrent_openai", max_concurrent_openai),
            Settings.max_concurrent_openai,
        ),
        per_row_delay_sec=to_float(
            "per_row_delay_sec",
            pick("per_row_delay_sec", per_row_delay_sec),
            Settings.per_row_delay_sec,
        ),
        checkpoint_every=to_int(
            "checkpoint_every",
            pick("checkpoint_every", checkpoint_every),
            Settings.checkpoint_every,
        ),
        enable_resume=to_bool(
            "enable_resume", pick("enable_resume", enable_resume), Settings.enable_resume
        ),
        enable_jina_cache=to_bool(
            "enable_jina_cache",
            pick("enable_jina_cache", enable_jina_cache),
            Settings.enable_jina_cache,
        ),
        cache_dir=to_path("cache_dir", pick("cache_dir", cache_dir), Settings.cache_dir),
        max_retries=to_int(
            "max_retries", pick("max_retries", max_retries), Settings.max_retries
        ),
        retry_initial_wait=to_float(
            "retry_initial_wait",
            pick("retry_initial_wait", retry_initial_wait),
            Settings.retry_initial_wait,
        ),
        retry_max_wait=to_float(
            "retry_max_wait", pick("retry_max_wait", retry_max_wait), Settings.retry_max_wait
        ),
        max_content_chars=to_int(
            "max_content_chars",
            pick("max_content_chars", max_content_chars),
            Settings.max_content_chars,
        ),
        log_level=str(pick("log_level", log_level) or Settings.log_level),
    )

    return cfg


def require_keys(cfg: Settings) -> None:
    if not cfg.jina_api_key:
        raise ConfigError(
            "Missing Jina API key. Set JINA_API_KEY (or STAFF_FINDER_JINA_API_KEY) "
            "or add jina_api_key to config.toml."
        )
    if not cfg.openai_api_key:
        raise ConfigError(
            "Missing OpenAI API key. Set OPENAI_API_KEY (or STAFF_FINDER_OPENAI_API_KEY) "
            "or add openai_api_key to config.toml."
        )

    if cfg.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError("log_level must be one of DEBUG|INFO|WARNING|ERROR|CRITICAL")
    if cfg.openai_verbosity.lower() not in ("low", "medium", "high"):
        raise ConfigError("openai_verbosity must be one of low|medium|high")
    if cfg.openai_reasoning_effort.lower() not in ("low", "medium", "high"):
        raise ConfigError("openai_reasoning_effort must be one of low|medium|high")

    if cfg.checkpoint_every < 1:
        raise ConfigError("checkpoint_every must be >= 1")
    if cfg.max_concurrent_schools < 1:
        raise ConfigError("max_concurrent_schools must be >= 1")
    if cfg.max_concurrent_jina < 1:
        raise ConfigError("max_concurrent_jina must be >= 1")
    if cfg.max_concurrent_openai < 1:
        raise ConfigError("max_concurrent_openai must be >= 1")
