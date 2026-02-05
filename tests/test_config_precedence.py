from __future__ import annotations

from pathlib import Path

import pytest

from staff_finder import load_settings
from staff_finder.config import ConfigAuthError, ConfigValidationError


def _write_minimal_input(tmp_path: Path) -> tuple[Path, Path, Path]:
    input_csv = tmp_path / "schools.csv"
    input_csv.write_text("name,city,state\nTest School,Test City,TX\n", encoding="utf-8")

    prompt = tmp_path / "system_prompt.md"
    prompt.write_text("You are Staff Finder.", encoding="utf-8")

    output_csv = tmp_path / "out.csv"
    return input_csv, prompt, output_csv


def test_load_settings_precedence_explicit_over_env_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_csv, prompt, output_csv = _write_minimal_input(tmp_path)

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('openai_model = "file-model"\n', encoding="utf-8")

    import staff_finder.config as cfgmod

    monkeypatch.setattr(cfgmod, "default_config_paths", lambda: [cfg_path])
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    # Explicit wins
    cfg = load_settings(
        input_csv=str(input_csv),
        output_csv=str(output_csv),
        system_prompt_path=str(prompt),
        jina_api_key="jina",
        openai_api_key="openai",
        openai_model="explicit-model",
    )
    assert cfg.openai_model == "explicit-model"

    # Env wins over file
    cfg = load_settings(
        input_csv=str(input_csv),
        output_csv=str(output_csv),
        system_prompt_path=str(prompt),
        jina_api_key="jina",
        openai_api_key="openai",
        openai_model=None,
    )
    assert cfg.openai_model == "env-model"

    # File wins when env absent
    monkeypatch.delenv("OPENAI_MODEL")
    cfg = load_settings(
        input_csv=str(input_csv),
        output_csv=str(output_csv),
        system_prompt_path=str(prompt),
        jina_api_key="jina",
        openai_api_key="openai",
        openai_model=None,
    )
    assert cfg.openai_model == "file-model"


def test_load_settings_default_model_when_not_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_csv, prompt, output_csv = _write_minimal_input(tmp_path)

    import staff_finder.config as cfgmod

    monkeypatch.setattr(cfgmod, "default_config_paths", lambda: [])
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    cfg = load_settings(
        input_csv=str(input_csv),
        output_csv=str(output_csv),
        system_prompt_path=str(prompt),
        jina_api_key="jina",
        openai_api_key="openai",
    )
    assert cfg.openai_model == "gpt-4o-mini"


def test_load_settings_missing_keys_is_auth_error(tmp_path: Path):
    input_csv, prompt, output_csv = _write_minimal_input(tmp_path)

    with pytest.raises(ConfigAuthError):
        load_settings(
            input_csv=str(input_csv),
            output_csv=str(output_csv),
            system_prompt_path=str(prompt),
        )


def test_validate_settings_retry_wait_relationship(tmp_path: Path):
    input_csv, prompt, output_csv = _write_minimal_input(tmp_path)

    with pytest.raises(ConfigValidationError):
        load_settings(
            input_csv=str(input_csv),
            output_csv=str(output_csv),
            system_prompt_path=str(prompt),
            jina_api_key="jina",
            openai_api_key="openai",
            retry_initial_wait=10,
            retry_max_wait=1,
        )
