from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx  # type: ignore
import pandas as pd  # type: ignore
import typer
from dotenv import load_dotenv  # type: ignore
from tqdm import tqdm  # type: ignore

from .config import ConfigAuthError, ConfigError, ConfigValidationError, Settings, load_settings, require_keys
from .io_csv import ensure_output_columns, load_df, save_df
from .limiters import Limiters
from .logging_setup import setup_logging
from .models import map_headers
from .resolver import resolve_for_school_async

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Staff Finder CLI."""
    return


NULLISH = {"", "nan", "none", "not_found", "error_not_found"}


class ExitCode:
    SUCCESS = 0
    VALIDATION = 2
    API_OR_AUTH = 3
    NETWORK = 4
    UNEXPECTED = 5


def _default_output_path(input_csv: Path) -> Path:
    return input_csv.with_name(input_csv.stem + "_with_urls" + input_csv.suffix)


def _redact_secret(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return v[:3] + "…" + v[-2:]


async def _worker(
    idx: int,
    row: pd.Series,
    cols: tuple[str, str, str],
    cfg: Settings,
    lim: Limiters,
    results: dict[int, tuple[str, str, str]],
) -> None:
    async with lim.sem_schools:
        try:
            school = map_headers(row)
            result = await resolve_for_school_async(cfg, school, lim)
            results[idx] = (result.url, result.confidence or "", result.reasoning)
        except Exception as e:
            results[idx] = ("ERROR_NOT_FOUND", "", str(e))


async def _flush_results(
    df: pd.DataFrame,
    cols: tuple[str, str, str],
    results: dict[int, tuple[str, str, str]],
    output_csv: str,
) -> None:
    url_col, conf_col, reason_col = cols
    if not results:
        return

    for i, (url, conf, reason) in results.items():
        df.at[i, url_col] = url
        df.at[i, conf_col] = conf
        df.at[i, reason_col] = reason

    save_df(df, output_csv)
    results.clear()


async def run_async(cfg: Settings, *, show_progress: bool) -> dict[str, Any]:
    setup_logging(
        log_file="run.log",
        console=(cfg.log_level.upper() == "DEBUG"),
        log_level=cfg.log_level,
    )
    require_keys(cfg)

    input_path = Path(cfg.input_csv)
    output_path = Path(cfg.output_csv)

    if cfg.enable_resume and output_path.exists():
        df = load_df(str(output_path))
        source_path = output_path
    else:
        df = load_df(str(input_path))
        source_path = input_path

    cols = ensure_output_columns(df)
    url_col = cols[0]
    lim = Limiters.from_settings(cfg)

    pending_rows: list[tuple[int, pd.Series]] = []
    for idx, row in df.iterrows():
        val = row.get(url_col, "")
        existing = "" if pd.isna(val) else str(val).strip()
        if existing == "" or existing.lower() in NULLISH:
            pending_rows.append((idx, row))

    results: dict[int, tuple[str, str, str]] = {}
    in_flight: set[asyncio.Task[Any]] = set()
    completed_since_checkpoint = 0

    pbar = tqdm(
        total=len(pending_rows),
        desc="Finding staff directories",
        disable=not show_progress,
    )

    async def spawn(i: int, r: pd.Series) -> asyncio.Task[Any]:
        return asyncio.create_task(_worker(i, r, cols, cfg, lim, results))

    try:
        it = iter(pending_rows)
        for _ in range(min(cfg.max_concurrent_schools, len(pending_rows))):
            i, r = next(it)
            in_flight.add(await spawn(i, r))

        while in_flight:
            done, in_flight = await asyncio.wait(
                in_flight,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if show_progress:
                pbar.update(len(done))
            completed_since_checkpoint += len(done)

            for _ in range(len(done)):
                try:
                    i, r = next(it)
                except StopIteration:
                    break
                in_flight.add(await spawn(i, r))

            if completed_since_checkpoint >= cfg.checkpoint_every:
                await _flush_results(df, cols, results, cfg.output_csv)
                completed_since_checkpoint = 0

        await _flush_results(df, cols, results, cfg.output_csv)

    except KeyboardInterrupt:
        await _flush_results(df, cols, results, cfg.output_csv)
        raise

    # Summary counts
    urls = df[url_col].astype(str).fillna("").str.strip().str.lower()
    found = int(((urls != "") & (~urls.isin({"not_found", "error_not_found"}))).sum())
    not_found = int((urls == "not_found").sum())
    errors = int((urls == "error_not_found").sum())

    return {
        "input_csv": str(input_path),
        "output_csv": str(output_path),
        "source_loaded": str(source_path),
        "rows_total": int(len(df)),
        "rows_pending": int(len(pending_rows)),
        "rows_found": found,
        "rows_not_found": not_found,
        "rows_error": errors,
        "output_url_column": url_col,
    }


@app.command()
def run(
    input_csv: Path = typer.Argument(..., exists=True, dir_okay=False, help="Input CSV."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        dir_okay=False,
        help="Output CSV path (default: <input>_with_urls.csv).",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        dir_okay=False,
        help=(
            "Optional config.toml path. Default search: "
            "~/.config/staff-finder/config.toml then ~/.staff-finder.toml."
        ),
    ),
    jina_api_key: str | None = typer.Option(
        None,
        "--jina-api-key",
        help="Jina API key (required; can also come from env/config).",
    ),
    openai_api_key: str | None = typer.Option(
        None,
        "--openai-api-key",
        help="OpenAI API key (required; can also come from env/config).",
    ),
    openai_model: str | None = typer.Option(
        None,
        "--openai-model",
        help="OpenAI model to use (default: gpt-4o-mini; can also come from env/config).",
    ),
    max_concurrent: int | None = typer.Option(
        None,
        "--max-concurrent",
        min=1,
        help="Max concurrent schools (default: 5; can also come from env/config).",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable verbose logging."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
    debug: bool = typer.Option(False, "--debug", help="Print debug metadata (redacted)."),
) -> None:
    """Discover staff directory URLs for schools in a CSV."""

    # Optional local dev convenience: load .env into env vars.
    # Precedence is still: flags -> env -> config.toml -> defaults.
    load_dotenv(override=False)

    output_csv = str(output) if output else str(_default_output_path(input_csv))

    try:
        cfg = load_settings(
            config_path=config,
            input_csv=str(input_csv),
            output_csv=output_csv,
            jina_api_key=jina_api_key,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            max_concurrent_schools=max_concurrent,
            log_level="DEBUG" if verbose else None,
        )
    except ConfigAuthError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.API_OR_AUTH) from e
    except ConfigValidationError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e
    except ConfigError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e

    if debug:
        typer.echo("Debug:")
        typer.echo(f"- openai_api_key={_redact_secret(cfg.openai_api_key)}")
        typer.echo(f"- jina_api_key={_redact_secret(cfg.jina_api_key)}")
        typer.echo(f"- openai_model={cfg.openai_model}")
        typer.echo(f"- max_concurrent_schools={cfg.max_concurrent_schools}")
        typer.echo(f"- config={str(config) if config else '(auto)'}")

    try:
        summary = asyncio.run(run_async(cfg, show_progress=not json_output))
    except FileNotFoundError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e
    except ConfigAuthError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.API_OR_AUTH) from e
    except ConfigValidationError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e
    except ConfigError as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.VALIDATION) from e
    except (httpx.ReadTimeout, httpx.ConnectError) as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.NETWORK) from e
    except KeyboardInterrupt:
        typer.echo("Interrupted. Partial results saved.")
        raise typer.Exit(ExitCode.SUCCESS) from None
    except Exception as e:
        typer.echo(str(e))
        raise typer.Exit(ExitCode.UNEXPECTED) from e

    if json_output:
        typer.echo(json.dumps(summary, indent=2, sort_keys=True))
    else:
        typer.echo(f"Loaded: {summary['source_loaded']}")
        typer.echo(f"Output: {summary['output_csv']}")
        typer.echo(
            f"Rows: total={summary['rows_total']} pending={summary['rows_pending']} "
            f"found={summary['rows_found']} not_found={summary['rows_not_found']} "
            f"error={summary['rows_error']}"
        )
