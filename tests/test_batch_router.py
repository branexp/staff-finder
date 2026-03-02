"""Tests for batch_router orchestration using monkeypatched batchctl."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from staff_finder.batch_router import (
    BatchRunState,
    _read_state,
    _state_path,
    _write_state,
    resume_batch_task,
    start_batch_task,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_batchctl_mock(
    *,
    openai_batch_id: str = "batch_abc123",
    batch_id: int = 42,
    status_value: str = "in_progress",
    is_complete: bool = False,
    is_successful: bool = False,
    output_jsonl: Path | None = None,
) -> dict[str, Any]:
    """Build a minimal batchctl mock dictionary."""

    # --- ShardConfig, JsonlGenerator, load_dataset ---
    shard_config_instance = MagicMock()
    ShardConfig = MagicMock(return_value=shard_config_instance)

    mock_file = MagicMock()
    mock_file.path = MagicMock()
    mock_file.path.resolve.return_value = Path("/tmp/fake.jsonl")

    summary = MagicMock()
    summary.files = [mock_file]

    generator_instance = MagicMock()
    generator_instance.generate.return_value = summary
    JsonlGenerator = MagicMock(return_value=generator_instance)

    load_dataset = MagicMock(return_value=MagicMock())

    # --- batch record ---
    batch_record = MagicMock()
    batch_record.id = batch_id
    batch_record.openai_batch_id = openai_batch_id

    # --- lifecycle ---
    lifecycle_instance = MagicMock()
    lifecycle_instance.process_generation.return_value = [batch_record]

    # status
    status = MagicMock()
    status.batch_info.status.value = status_value
    status.is_complete = is_complete
    status.is_successful = is_successful
    lifecycle_instance.sync_status.return_value = status

    # download
    download = MagicMock()
    download.files = {"output": output_jsonl}
    lifecycle_instance.download_results.return_value = download

    BatchLifecycleManager = MagicMock(return_value=lifecycle_instance)

    # --- registry ---
    registry_batch = MagicMock()
    registry_batch.id = batch_id

    registry_instance = MagicMock()
    registry_instance.get_batch_by_openai_id.return_value = registry_batch
    JobRegistry = MagicMock(return_value=registry_instance)

    return {
        "OpenAIClient": MagicMock(),
        "ShardConfig": ShardConfig,
        "JsonlGenerator": JsonlGenerator,
        "BatchLifecycleManager": BatchLifecycleManager,
        "load_dataset": load_dataset,
        "reconcile_batch_results": MagicMock(),
        "JobRegistry": JobRegistry,
        # expose internals for assertion convenience
        "_summary": summary,
        "_lifecycle": lifecycle_instance,
        "_ShardConfig": ShardConfig,
    }


def _make_preprocess_result(tmp_path: Path) -> Any:
    processed_csv = tmp_path / "processed.csv"
    pd.DataFrame([{"district_name": "Acme ISD", "state_abbr": "TX"}]).to_csv(
        processed_csv, index=False
    )
    result = MagicMock()
    result.processed_csv = processed_csv
    return result


# ---------------------------------------------------------------------------
# start_batch_task
# ---------------------------------------------------------------------------


def test_start_batch_task_creates_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """start_batch_task should write a state JSON and return the openai_batch_id."""
    input_csv = tmp_path / "schools.csv"
    pd.DataFrame([{"district_name": "Acme ISD", "state_abbr": "TX"}]).to_csv(input_csv, index=False)

    batchctl_mock = _make_batchctl_mock(openai_batch_id="batch_test001")
    preprocess_result = _make_preprocess_result(tmp_path)

    task_mock = MagicMock()
    task_mock.preprocess_data.return_value = preprocess_result
    task_mock.load_prompt_templates.return_value = ("sys", "user")

    # Redirect state dir into tmp_path
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("staff_finder.batch_router._import_batchctl", lambda: batchctl_mock)
    monkeypatch.setattr("staff_finder.batch_router.get_task", lambda _name: task_mock)

    returned_id = start_batch_task(
        "district_enrichment",
        input_csv,
        openai_api_key="sk_test",
        openai_model="gpt-4o-mini",
        max_jina_workers=1,
    )

    assert returned_id == "batch_test001"
    state_file = _state_path("batch_test001")
    assert state_file.exists(), f"State file not found: {state_file}"

    state = _read_state("batch_test001")
    assert state.task_name == "district_enrichment"
    assert state.openai_batch_id == "batch_test001"
    assert state.completed_at is None


def test_start_batch_task_per_run_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two consecutive start calls should produce distinct per-run directories."""
    import datetime as dt_module

    input_csv = tmp_path / "schools.csv"
    pd.DataFrame([{"district_name": "Acme ISD", "state_abbr": "TX"}]).to_csv(input_csv, index=False)

    captured_dirs: list[Path] = []

    call_count = [0]

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            idx = call_count[0]
            call_count[0] += 1
            # Each call gets a unique second value so run dirs never collide
            return dt_module.datetime(2026, 1, 1, 0, 0, idx + 1, tzinfo=dt_module.UTC)

    monkeypatch.setattr("staff_finder.batch_router.datetime", FakeDatetime)

    def capturing_preprocess(input_path: Path, work_dir: Path, *, max_workers: int):
        captured_dirs.append(work_dir)
        return _make_preprocess_result(tmp_path)

    monkeypatch.chdir(tmp_path)

    for batch_id in ("batch_run1", "batch_run2"):
        batchctl_mock = _make_batchctl_mock(openai_batch_id=batch_id)
        task_mock = MagicMock()
        task_mock.preprocess_data.side_effect = capturing_preprocess
        task_mock.load_prompt_templates.return_value = ("sys", "user")
        monkeypatch.setattr(
            "staff_finder.batch_router._import_batchctl", lambda bm=batchctl_mock: bm
        )
        monkeypatch.setattr("staff_finder.batch_router.get_task", lambda _name, tm=task_mock: tm)
        start_batch_task(
            "district_enrichment",
            input_csv,
            openai_api_key="sk_test",
            openai_model="gpt-4o-mini",
            max_jina_workers=1,
        )

    assert len(captured_dirs) == 2
    assert captured_dirs[0] != captured_dirs[1], "Each run must use a distinct directory"


def test_start_batch_task_shard_config_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ShardConfig limits must stay within OpenAI batch API caps."""
    input_csv = tmp_path / "schools.csv"
    pd.DataFrame([{"district_name": "Acme ISD", "state_abbr": "TX"}]).to_csv(input_csv, index=False)

    batchctl_mock = _make_batchctl_mock()
    preprocess_result = _make_preprocess_result(tmp_path)
    task_mock = MagicMock()
    task_mock.preprocess_data.return_value = preprocess_result
    task_mock.load_prompt_templates.return_value = ("sys", "user")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("staff_finder.batch_router._import_batchctl", lambda: batchctl_mock)
    monkeypatch.setattr("staff_finder.batch_router.get_task", lambda _name: task_mock)

    start_batch_task(
        "district_enrichment",
        input_csv,
        openai_api_key="sk_test",
        openai_model="gpt-4o-mini",
        max_jina_workers=1,
    )

    _ShardConfig = batchctl_mock["_ShardConfig"]
    assert _ShardConfig.called
    kwargs = _ShardConfig.call_args[1] if _ShardConfig.call_args[1] else {}
    if kwargs:
        assert kwargs.get("max_requests_per_file", 0) <= 50_000
        assert kwargs.get("max_bytes_per_file", 0) <= 100_000_000


# ---------------------------------------------------------------------------
# resume_batch_task
# ---------------------------------------------------------------------------


def test_resume_batch_task_in_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resume should return status without postprocessing when batch is in_progress."""
    monkeypatch.chdir(tmp_path)

    state = BatchRunState(
        task_name="district_enrichment",
        input_csv=str(tmp_path / "input.csv"),
        processed_csv=str(tmp_path / "processed.csv"),
        output_csv=str(tmp_path / "output.csv"),
        jsonl_path=str(tmp_path / "req.jsonl"),
        local_batch_id="42",
        openai_batch_id="batch_inprog",
        registry_path=str(tmp_path / "registry.json"),
        artifacts_dir=str(tmp_path / "artifacts"),
        created_at="2026-01-01T00:00:00+00:00",
    )
    _write_state(state)

    batchctl_mock = _make_batchctl_mock(
        openai_batch_id="batch_inprog",
        status_value="in_progress",
        is_complete=False,
    )
    task_mock = MagicMock()
    monkeypatch.setattr("staff_finder.batch_router._import_batchctl", lambda: batchctl_mock)
    monkeypatch.setattr("staff_finder.batch_router.get_task", lambda _name: task_mock)

    result = resume_batch_task("batch_inprog", task_name="district_enrichment", openai_api_key="sk")
    assert result.status == "in_progress"
    assert result.output_csv is None
    task_mock.postprocess_data.assert_not_called()


def test_resume_batch_task_complete_postprocesses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resume should postprocess and update state when the batch completes successfully."""
    monkeypatch.chdir(tmp_path)

    input_csv = tmp_path / "input.csv"
    processed_csv = tmp_path / "processed.csv"
    output_csv = tmp_path / "output.csv"
    output_jsonl = tmp_path / "results.jsonl"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    output_jsonl.write_text("{}")

    pd.DataFrame([{"district_name": "Acme", "state_abbr": "TX"}]).to_csv(input_csv, index=False)
    pd.DataFrame([{"district_name": "Acme", "state_abbr": "TX"}]).to_csv(processed_csv, index=False)

    state = BatchRunState(
        task_name="district_enrichment",
        input_csv=str(input_csv),
        processed_csv=str(processed_csv),
        output_csv=str(output_csv),
        jsonl_path=str(tmp_path / "req.jsonl"),
        local_batch_id="42",
        openai_batch_id="batch_done",
        registry_path=str(tmp_path / "registry.json"),
        artifacts_dir=str(artifacts_dir),
        created_at="2026-01-01T00:00:00+00:00",
    )
    _write_state(state)

    # reconcile will write a merged CSV
    def fake_reconcile(**kwargs: Any) -> None:
        merged: Path = kwargs["merged_path"]
        pd.DataFrame(
            [{"source_index": 0, "status": "success", "output_content": '{"acronym":"AISD"}'}]
        ).to_csv(merged, index=False)

    expected_output = tmp_path / "postprocessed.csv"
    task_mock = MagicMock()
    from staff_finder.batch_tasks import PostprocessResult

    task_mock.postprocess_data.return_value = PostprocessResult(
        output_csv=expected_output,
        rows_processed=1,
        rows_succeeded=1,
        rows_failed=0,
    )

    batchctl_mock = _make_batchctl_mock(
        openai_batch_id="batch_done",
        status_value="completed",
        is_complete=True,
        is_successful=True,
        output_jsonl=output_jsonl,
    )
    batchctl_mock["reconcile_batch_results"] = MagicMock(side_effect=fake_reconcile)

    monkeypatch.setattr("staff_finder.batch_router._import_batchctl", lambda: batchctl_mock)
    monkeypatch.setattr("staff_finder.batch_router.get_task", lambda _name: task_mock)

    result = resume_batch_task("batch_done", task_name="district_enrichment", openai_api_key="sk")
    assert result.status == "completed"
    assert result.output_csv == expected_output

    # State file should now have completed_at and merged_csv set
    updated_state = _read_state("batch_done")
    assert updated_state.completed_at is not None
    assert updated_state.merged_csv is not None
