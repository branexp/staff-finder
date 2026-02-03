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
    output_csv: str = ""
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
    xdg = pathlib.Path(user_config_dir("staff-finder")) / "config.toml"
    legacy = pathlib.Path.home() / ".staff-finder.toml"
    return [xdg, legacy]


def _coerce_bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "on"}:
            return True
        if v in {"false", "0", "no", "off"}:
            return False
    raise ConfigError(f"{name} must be a boolean")


def _coerce_int(value: Any, *, name: str) -> int:
    try:
        return int(value)
    except Exception as e:
        raise ConfigError(f"{name} must be an integer") from e


def _coerce_float(value: Any, *, name: str) -> float:
    try:
        return float(value)
    except Exception as e:
        raise ConfigError(f"{name} must be a number") from e


def _pick(*, explicit: Any, env: Any, file: Any) -> Any:
    if explicit is not None:
        return explicit
    if env not in (None, ""):
        return env
    if file not in (None, ""):
        return file
    return None


def load_settings(
    *,
    # IO
    input_csv: str | None = None,
    output_csv: str | None = None,
    system_prompt_path: str | None = None,
    # Keys
    jina_api_key: str | None = None,
    openai_api_key: str | None = None,
    # OpenAI
    openai_model: str | None = None,
    openai_verbosity: str | None = None,
    openai_reasoning_effort: str | None = None,
    openai_request_timeout: float | None = None,
    # Jina
    jina_base_url: str | None = None,
    jina_no_cache: bool | None = None,
    jina_request_timeout: float | None = None,
    # Planner
    max_queries_per_school: int | None = None,
    candidates_for_selection: int | None = None,
    # Concurrency
    max_concurrent_schools: int | None = None,
    max_concurrent_jina: int | None = None,
    max_concurrent_openai: int | None = None,
    # Pacing/checkpoint
    per_row_delay_sec: float | None = None,
    checkpoint_every: int | None = None,
    enable_resume: bool | None = None,
    # Cache
    enable_jina_cache: bool | None = None,
    cache_dir: str | pathlib.Path | None = None,
    # Retry
    max_retries: int | None = None,
    retry_initial_wait: float | None = None,
    retry_max_wait: float | None = None,
    # Content truncation
    max_content_chars: int | None = None,
    # Logging
    log_level: str | None = None,
) -> Settings:
    """Load settings using precedence:

    1) explicit args (CLI)
    2) env vars
    3) config file(s)
    4) defaults

    Config files (low → high precedence):
    - ~/.config/staff-finder/config.toml
    - ~/.staff-finder.toml
    """

    file_cfg: dict[str, Any] = {}
    for p in default_config_paths():
        file_cfg.update(_load_toml(p))

    env_cfg: dict[str, Any] = {
        # IO
        "input_csv": os.getenv("INPUT_CSV"),
        "output_csv": os.getenv("OUTPUT_CSV"),
        "system_prompt_path": os.getenv("SYSTEM_PROMPT_PATH"),
        # Keys
        "jina_api_key": os.getenv("JINA_API_KEY"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        # OpenAI
        "openai_model": os.getenv("OPENAI_MODEL"),
        "openai_verbosity": os.getenv("OPENAI_VERBOSITY"),
        "openai_reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT"),
        "openai_request_timeout": os.getenv("OPENAI_REQUEST_TIMEOUT"),
        # Jina
        "jina_base_url": os.getenv("JINA_BASE_URL"),
        "jina_no_cache": os.getenv("JINA_NO_CACHE"),
        "jina_request_timeout": os.getenv("JINA_REQUEST_TIMEOUT"),
        # Planner
        "max_queries_per_school": os.getenv("MAX_QUERIES_PER_SCHOOL"),
        "candidates_for_selection": os.getenv("CANDIDATES_FOR_SELECTION"),
        # Concurrency
        "max_concurrent_schools": os.getenv("MAX_CONCURRENT_SCHOOLS"),
        "max_concurrent_jina": os.getenv("MAX_CONCURRENT_JINA"),
        "max_concurrent_openai": os.getenv("MAX_CONCURRENT_OPENAI"),
        # Pacing/checkpoint
        "per_row_delay_sec": os.getenv("PER_ROW_DELAY_SEC"),
        "checkpoint_every": os.getenv("CHECKPOINT_EVERY"),
        "enable_resume": os.getenv("ENABLE_RESUME"),
        # Cache
        "enable_jina_cache": os.getenv("ENABLE_JINA_CACHE"),
        "cache_dir": os.getenv("CACHE_DIR"),
        # Retry
        "max_retries": os.getenv("MAX_RETRIES"),
        "retry_initial_wait": os.getenv("RETRY_INITIAL_WAIT"),
        "retry_max_wait": os.getenv("RETRY_MAX_WAIT"),
        # Content truncation
        "max_content_chars": os.getenv("MAX_CONTENT_CHARS"),
        # Logging
        "log_level": os.getenv("LOG_LEVEL"),
    }

    def pick(key: str, explicit_value: Any) -> Any:
        return _pick(explicit=explicit_value, env=env_cfg.get(key), file=file_cfg.get(key))

    # Start with defaults, then fill.
    cfg = Settings()

    cfg.input_csv = str(pick("input_csv", input_csv) or cfg.input_csv)
    out = pick("output_csv", output_csv)
    if out is None:
        # If not provided via CLI/env/config, derive from input.
        in_path = pathlib.Path(cfg.input_csv)
        cfg.output_csv = str(in_path.with_name(in_path.stem + "_with_urls" + in_path.suffix))
    else:
        cfg.output_csv = str(out)
    cfg.system_prompt_path = str(
        pick("system_prompt_path", system_prompt_path) or cfg.system_prompt_path
    )

    cfg.jina_api_key = pick("jina_api_key", jina_api_key) or cfg.jina_api_key
    cfg.openai_api_key = pick("openai_api_key", openai_api_key) or cfg.openai_api_key

    cfg.openai_model = str(pick("openai_model", openai_model) or cfg.openai_model)
    cfg.openai_verbosity = str(pick("openai_verbosity", openai_verbosity) or cfg.openai_verbosity)
    cfg.openai_reasoning_effort = str(
        pick("openai_reasoning_effort", openai_reasoning_effort) or cfg.openai_reasoning_effort
    )

    ort = pick("openai_request_timeout", openai_request_timeout)
    if ort is not None:
        cfg.openai_request_timeout = _coerce_float(ort, name="openai_request_timeout")

    cfg.jina_base_url = str(pick("jina_base_url", jina_base_url) or cfg.jina_base_url).rstrip("/")

    jnc = pick("jina_no_cache", jina_no_cache)
    if jnc is not None:
        cfg.jina_no_cache = _coerce_bool(jnc, name="jina_no_cache")

    jrt = pick("jina_request_timeout", jina_request_timeout)
    if jrt is not None:
        cfg.jina_request_timeout = _coerce_float(jrt, name="jina_request_timeout")

    mq = pick("max_queries_per_school", max_queries_per_school)
    if mq is not None:
        cfg.max_queries_per_school = _coerce_int(mq, name="max_queries_per_school")

    cfs = pick("candidates_for_selection", candidates_for_selection)
    if cfs is not None:
        cfg.candidates_for_selection = _coerce_int(cfs, name="candidates_for_selection")

    mcs = pick("max_concurrent_schools", max_concurrent_schools)
    if mcs is not None:
        cfg.max_concurrent_schools = _coerce_int(mcs, name="max_concurrent_schools")

    mcj = pick("max_concurrent_jina", max_concurrent_jina)
    if mcj is not None:
        cfg.max_concurrent_jina = _coerce_int(mcj, name="max_concurrent_jina")

    mco = pick("max_concurrent_openai", max_concurrent_openai)
    if mco is not None:
        cfg.max_concurrent_openai = _coerce_int(mco, name="max_concurrent_openai")

    prd = pick("per_row_delay_sec", per_row_delay_sec)
    if prd is not None:
        cfg.per_row_delay_sec = _coerce_float(prd, name="per_row_delay_sec")

    ce = pick("checkpoint_every", checkpoint_every)
    if ce is not None:
        cfg.checkpoint_every = _coerce_int(ce, name="checkpoint_every")

    er = pick("enable_resume", enable_resume)
    if er is not None:
        cfg.enable_resume = _coerce_bool(er, name="enable_resume")

    ejc = pick("enable_jina_cache", enable_jina_cache)
    if ejc is not None:
        cfg.enable_jina_cache = _coerce_bool(ejc, name="enable_jina_cache")

    cd = pick("cache_dir", cache_dir)
    if cd is not None:
        cfg.cache_dir = pathlib.Path(str(cd))

    mr = pick("max_retries", max_retries)
    if mr is not None:
        cfg.max_retries = _coerce_int(mr, name="max_retries")

    riw = pick("retry_initial_wait", retry_initial_wait)
    if riw is not None:
        cfg.retry_initial_wait = _coerce_float(riw, name="retry_initial_wait")

    rmw = pick("retry_max_wait", retry_max_wait)
    if rmw is not None:
        cfg.retry_max_wait = _coerce_float(rmw, name="retry_max_wait")

    mcc = pick("max_content_chars", max_content_chars)
    if mcc is not None:
        cfg.max_content_chars = _coerce_int(mcc, name="max_content_chars")

    cfg.log_level = str(pick("log_level", log_level) or cfg.log_level)

    validate_settings(cfg)
    return cfg


def validate_settings(cfg: Settings) -> None:
    if not cfg.jina_api_key:
        raise ConfigError("Missing JINA_API_KEY")
    if not cfg.openai_api_key:
        raise ConfigError("Missing OPENAI_API_KEY")

    if cfg.max_concurrent_schools < 1:
        raise ConfigError("max_concurrent_schools must be >= 1")
    if cfg.max_concurrent_jina < 1:
        raise ConfigError("max_concurrent_jina must be >= 1")
    if cfg.max_concurrent_openai < 1:
        raise ConfigError("max_concurrent_openai must be >= 1")

    if cfg.checkpoint_every < 1:
        raise ConfigError("checkpoint_every must be >= 1")

    if cfg.openai_verbosity.lower() not in {"low", "medium", "high"}:
        raise ConfigError("OPENAI_VERBOSITY must be one of: low, medium, high")
    if cfg.openai_reasoning_effort.lower() not in {"low", "medium", "high"}:
        raise ConfigError("OPENAI_REASONING_EFFORT must be one of: low, medium, high")

    if cfg.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("LOG_LEVEL must be DEBUG|INFO|WARNING|ERROR|CRITICAL")
