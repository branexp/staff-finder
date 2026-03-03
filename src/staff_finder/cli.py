from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import load_dotenv  # type: ignore

from .batch_router import resume_batch_task, start_batch_task
from .batch_tasks import get_task, list_tasks
from .config import (
    ConfigAuthError,
    ConfigError,
    ConfigValidationError,
    load_settings,
    require_keys,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)
batch_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(batch_app, name="batch")


@app.callback()
def main() -> None:
    """Staff Finder CLI."""
    return


class ExitCode:
    SUCCESS = 0
    VALIDATION = 2
    API_OR_AUTH = 3
    NETWORK = 4
    UNEXPECTED = 5


def _task_choices() -> str:
    tasks = list_tasks()
    return ", ".join(tasks) if tasks else "(none)"


def _redact_secret(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return v[:3] + "…" + v[-2:]


@batch_app.command("tasks")
def batch_tasks_list() -> None:
    """List available batch tasks with descriptions."""
    tasks = list_tasks()
    if not tasks:
        typer.echo("No batch tasks registered.")
        raise typer.Exit(0)

    for name in tasks:
        task = get_task(name)
        desc = getattr(task, "description", "(no description)")
        jina = " [Jina]" if getattr(task, "requires_jina", False) else ""
        cols = getattr(task, "output_columns", [])
        typer.echo(f"  {name}{jina}")
        typer.echo(f"    {desc}")
        if cols:
            typer.echo(f"    Output: {', '.join(cols)}")
        typer.echo()


@batch_app.command("start")
def batch_start(
    task_name: str = typer.Argument(
        ...,
        help="Task name. Use 'staff-finder batch tasks' to list available tasks.",
    ),
    input_csv: Path = typer.Argument(..., exists=True, dir_okay=False, help="Input CSV."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        dir_okay=False,
        help="Final enriched CSV output path.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        dir_okay=False,
        help="Optional config.toml path.",
    ),
    jina_api_key: str | None = typer.Option(
        None,
        "--jina-api-key",
        help="Jina API key override.",
    ),
    openai_api_key: str | None = typer.Option(
        None,
        "--openai-api-key",
        help="OpenAI API key override.",
    ),
    openai_model: str | None = typer.Option(
        None,
        "--openai-model",
        help="OpenAI model override.",
    ),
    max_concurrent_jina: int | None = typer.Option(
        None,
        "--max-concurrent-jina",
        min=1,
        max=20,
        help="Max concurrent Jina queries for preprocessing.",
    ),
) -> None:
    """Start a non-blocking batch job for a registered task."""
    load_dotenv(override=False)

    try:
        cfg = load_settings(
            config_path=config,
            input_csv=str(input_csv),
            output_csv=str(output) if output else None,
            jina_api_key=jina_api_key,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            max_concurrent_jina=max_concurrent_jina,
        )
        require_keys(cfg)
        if cfg.jina_api_key:
            os.environ["STAFF_FINDER_JINA_API_KEY"] = cfg.jina_api_key
    except ConfigAuthError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.API_OR_AUTH) from e
    except (ConfigValidationError, ConfigError) as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e

    try:
        batch_id = start_batch_task(
            task_name,
            input_csv,
            openai_api_key=cfg.openai_api_key or "",
            # Pass an explicit model only when the user provided one (CLI flag or env var);
            # otherwise pass None so the task's TaskConfig.default_model is used.
            openai_model=(
                openai_model
                or os.getenv("STAFF_FINDER_OPENAI_MODEL")
                or os.getenv("OPENAI_MODEL")
                or None
            ),
            max_jina_workers=cfg.max_concurrent_jina,
            output_csv=output,
        )
    except KeyError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e
    except Exception as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.UNEXPECTED) from e

    typer.echo(batch_id)


@batch_app.command("resume")
def batch_resume(
    batch_id: str = typer.Argument(..., help="OpenAI batch ID returned by `batch start`."),
    task_name: str = typer.Option(
        ...,
        "--task",
        help="Task name used for this batch. Use 'staff-finder batch tasks' to list available tasks.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        dir_okay=False,
        help="Optional config.toml path.",
    ),
    openai_api_key: str | None = typer.Option(
        None,
        "--openai-api-key",
        help="OpenAI API key override.",
    ),
) -> None:
    """Resume/check a batch. Downloads and postprocesses when complete."""
    load_dotenv(override=False)

    try:
        cfg = load_settings(config_path=config, openai_api_key=openai_api_key)
        if not cfg.openai_api_key:
            raise ConfigAuthError(
                "Missing OpenAI API key. Set OPENAI_API_KEY (or STAFF_FINDER_OPENAI_API_KEY)."
            )
    except ConfigAuthError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.API_OR_AUTH) from e
    except (ConfigValidationError, ConfigError) as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e

    try:
        result = resume_batch_task(
            batch_id=batch_id,
            task_name=task_name,
            openai_api_key=cfg.openai_api_key,
        )
    except Exception as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.UNEXPECTED) from e

    if result.output_csv:
        typer.echo(f"completed: {result.status}")
        typer.echo(str(result.output_csv))
    else:
        typer.echo(f"status: {result.status}")
