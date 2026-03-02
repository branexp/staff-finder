from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore

from .batch_tasks import get_task


@dataclass
class BatchRunState:
    task_name: str
    input_csv: str
    processed_csv: str
    output_csv: str
    jsonl_path: str
    local_batch_id: str
    openai_batch_id: str
    registry_path: str
    artifacts_dir: str
    created_at: str
    merged_csv: str | None = None
    completed_at: str | None = None


@dataclass
class ResumeResult:
    status: str
    output_csv: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _state_dir() -> Path:
    path = Path(".staff_finder") / "batch_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(batch_id: str) -> Path:
    return _state_dir() / f"{batch_id}.json"


def _write_state(state: BatchRunState) -> None:
    _state_path(state.openai_batch_id).write_text(
        json.dumps(asdict(state), indent=2),
        encoding="utf-8",
    )


def _read_state(batch_id: str) -> BatchRunState:
    path = _state_path(batch_id)
    if not path.exists():
        raise FileNotFoundError(f"No saved state for batch_id={batch_id!r}. Expected file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BatchRunState(**payload)


def _import_batchctl() -> dict[str, Any]:
    try:
        from batchctl.core.clients.openai import OpenAIClient
        from batchctl.core.models.generation import ShardConfig
        from batchctl.core.services.generator import JsonlGenerator
        from batchctl.core.services.lifecycle import BatchLifecycleManager
        from batchctl.core.services.loaders import load_dataset
        from batchctl.core.services.reconciler import reconcile_batch_results
        from batchctl.core.services.registry import JobRegistry
    except Exception as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "batchctl is required. Install batchctl in the same Python environment "
            + "as staff-finder to use `staff-finder batch` commands."
        ) from e

    return {
        "OpenAIClient": OpenAIClient,
        "ShardConfig": ShardConfig,
        "JsonlGenerator": JsonlGenerator,
        "BatchLifecycleManager": BatchLifecycleManager,
        "load_dataset": load_dataset,
        "reconcile_batch_results": reconcile_batch_results,
        "JobRegistry": JobRegistry,
    }


def start_batch_task(
    task_name: str,
    input_csv: Path,
    *,
    openai_api_key: str,
    openai_model: str | None = None,
    max_jina_workers: int,
    output_csv: Path | None = None,
    batch_name: str | None = None,
) -> str:
    task = get_task(task_name)
    # Resolve model: explicit override → task default
    resolved_model = openai_model or task.config.default_model
    batchctl = _import_batchctl()

    _now = datetime.now(UTC)
    timestamp = _now.strftime("%Y%m%d_%H%M%S_") + f"{_now.microsecond // 1000:03d}"
    run_id = f"{task_name}_{timestamp}"
    base_dir = Path(".staff_finder") / task_name / run_id
    artifacts_dir = base_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    registry_path = base_dir / "registry.json"

    preprocess = task.preprocess_data(input_csv, base_dir, max_workers=max_jina_workers)
    system_template, user_template = task.load_prompt_templates()

    input_set = batchctl["load_dataset"](preprocess.processed_csv, format="csv")

    generator = batchctl["JsonlGenerator"](
        output_dir=artifacts_dir,
        shard_config=batchctl["ShardConfig"](
            max_requests_per_file=50_000,
            max_tokens_per_file=2_000_000,
            max_bytes_per_file=100_000_000,
        ),
    )
    resolved_batch_name = batch_name or run_id
    summary = generator.generate(
        input_set=input_set,
        batch_name=resolved_batch_name,
        model=resolved_model,
        system_template=system_template,
        user_template=user_template,
        response_format={"type": "json_object"},
    )
    if len(summary.files) != 1:
        raise RuntimeError(
            "This router expects a single JSONL output file. "
            + f"Generation produced {len(summary.files)} shards."
        )
    jsonl_path = summary.files[0].path

    registry = batchctl["JobRegistry"](registry_path)
    client = batchctl["OpenAIClient"](api_key=openai_api_key)
    lifecycle = batchctl["BatchLifecycleManager"](
        registry=registry, client=client, artifacts_dir=artifacts_dir
    )
    batch_records = lifecycle.process_generation(summary, auto_submit=True)
    if len(batch_records) != 1:
        raise RuntimeError(
            "This router expects a single submitted batch. "
            + f"Got {len(batch_records)} batch records."
        )
    batch_record = batch_records[0]
    if not batch_record.openai_batch_id:
        raise RuntimeError("Submitted batch is missing OpenAI batch ID.")

    final_output_csv = output_csv or input_csv.with_name(
        f"{input_csv.stem}_{task_name}_enriched{input_csv.suffix}"
    )
    state = BatchRunState(
        task_name=task_name,
        input_csv=str(input_csv.resolve()),
        processed_csv=str(preprocess.processed_csv.resolve()),
        output_csv=str(final_output_csv.resolve()),
        jsonl_path=str(jsonl_path.resolve()),
        local_batch_id=str(batch_record.id),
        openai_batch_id=batch_record.openai_batch_id,
        registry_path=str(registry_path.resolve()),
        artifacts_dir=str(artifacts_dir.resolve()),
        created_at=_utc_now_iso(),
    )
    _write_state(state)
    return batch_record.openai_batch_id


def resume_batch_task(batch_id: str, *, task_name: str, openai_api_key: str) -> ResumeResult:
    state = _read_state(batch_id)
    if state.task_name != task_name:
        raise ValueError(
            f"Batch {batch_id!r} belongs to task {state.task_name!r}, not {task_name!r}."
        )

    task = get_task(task_name)
    batchctl = _import_batchctl()

    registry = batchctl["JobRegistry"](Path(state.registry_path))
    client = batchctl["OpenAIClient"](api_key=openai_api_key)
    lifecycle = batchctl["BatchLifecycleManager"](
        registry=registry,
        client=client,
        artifacts_dir=Path(state.artifacts_dir),
    )

    batch = registry.get_batch_by_openai_id(batch_id)
    if batch is None:
        raise ValueError(f"Batch {batch_id!r} was not found in registry {state.registry_path}")

    status = lifecycle.sync_status(batch.id)
    status_value = status.batch_info.status.value
    if not status.is_complete:
        return ResumeResult(status=status_value)
    if not status.is_successful:
        return ResumeResult(status=status_value)

    download = lifecycle.download_results(batch.id, output_dir=Path(state.artifacts_dir))
    output_jsonl = download.files.get("output")
    if output_jsonl is None:
        raise RuntimeError("Batch completed but no output file was available for download.")

    merged_csv = Path(state.artifacts_dir) / f"{batch_id}_merged.csv"
    error_csv = Path(state.artifacts_dir) / f"{batch_id}_errors.csv"
    batchctl["reconcile_batch_results"](
        input_path=Path(state.processed_csv),
        output_path=output_jsonl,
        merged_path=merged_csv,
        error_path=error_csv,
        jsonl_path=Path(state.jsonl_path),
        output_format="csv",
        validate_output=True,
    )

    merged_df = pd.read_csv(merged_csv, dtype=object)
    original_df = pd.read_csv(Path(state.input_csv), dtype=object)
    result = task.postprocess_data(merged_df, original_df, Path(state.output_csv))

    state.merged_csv = str(merged_csv.resolve())
    state.completed_at = _utc_now_iso()
    _write_state(state)
    return ResumeResult(status=status_value, output_csv=result.output_csv, metadata=result.metadata)
