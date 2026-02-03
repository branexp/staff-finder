#!/usr/bin/env python3
"""CLI entry point for Staff Finder."""

import argparse
import asyncio
import os
from typing import Dict, Any, Tuple
from tqdm import tqdm  # type: ignore
import pandas as pd  # type: ignore

from .config import Settings, require_keys  # type: ignore
from .logging_setup import setup_logging  # type: ignore
from .io_csv import load_df, ensure_output_columns, save_df  # type: ignore
from .models import map_headers, SelectionResult  # type: ignore
from .resolver import resolve_for_school_async  # type: ignore
from .limiters import Limiters  # type: ignore

NULLISH = {"", "nan", "none", "not_found", "error_not_found"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="staff-finder",
        description="Async CLI tool that automatically discovers staff directory URLs for K-12 schools"
    )
    parser.add_argument(
        "input_csv",
        help="Path to input CSV file containing school records"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_csv",
        help="Output CSV file path (default: {input}_with_urls.csv)"
    )
    parser.add_argument(
        "--jina-api-key",
        dest="jina_api_key",
        help="Jina API key (or set JINA_API_KEY env var)"
    )
    parser.add_argument(
        "--openai-api-key",
        dest="openai_api_key",
        help="OpenAI API key (or set OPENAI_API_KEY env var)"
    )
    parser.add_argument(
        "--openai-model",
        dest="openai_model",
        help="OpenAI model to use (default: gpt-5-mini)"
    )
    parser.add_argument(
        "--max-concurrent",
        dest="max_concurrent",
        type=int,
        help="Max concurrent requests (default: 5)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    return parser.parse_args()


def apply_args_to_env(args: argparse.Namespace) -> None:
    """Apply CLI arguments to environment variables for Settings to pick up."""
    os.environ["INPUT_CSV"] = args.input_csv
    
    if args.output_csv:
        os.environ["OUTPUT_CSV"] = args.output_csv
    elif "OUTPUT_CSV" not in os.environ:
        # Generate default output filename
        import pathlib
        input_path = pathlib.Path(args.input_csv)
        default_output = input_path.stem + "_with_urls" + input_path.suffix
        os.environ["OUTPUT_CSV"] = default_output
    
    if args.jina_api_key:
        os.environ["JINA_API_KEY"] = args.jina_api_key
    
    if args.openai_api_key:
        os.environ["OPENAI_API_KEY"] = args.openai_api_key
    
    if args.openai_model:
        os.environ["OPENAI_MODEL"] = args.openai_model
    
    if args.max_concurrent:
        os.environ["MAX_CONCURRENT_SCHOOLS"] = str(args.max_concurrent)
    
    if args.verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"


async def _worker(
    idx: int, 
    row: pd.Series, 
    cols: Tuple[str, str, str], 
    cfg: Settings, 
    lim: Limiters, 
    results: Dict[int, Tuple[str, str, str]]
) -> None:
    """Process a single school row."""
    async with lim.sem_schools:
        try:
            school = map_headers(row)
            result = await resolve_for_school_async(cfg, school)
            results[idx] = (result.url, result.confidence or "", result.reasoning)
        except Exception as e:
            results[idx] = ("ERROR_NOT_FOUND", "", str(e))


async def _flush_results(
    df: pd.DataFrame, 
    cols: Tuple[str, str, str], 
    results: Dict[int, Tuple[str, str, str]], 
    output_csv: str
) -> None:
    """Flush accumulated results to CSV."""
    url_col, conf_col, reason_col = cols
    if results:
        for i, (url, conf, reason) in results.items():
            df.at[i, url_col] = url
            df.at[i, conf_col] = conf
            df.at[i, reason_col] = reason
        save_df(df, output_csv)
        results.clear()


async def main_async() -> None:
    """Main async entry point."""
    cfg = Settings()
    # If user sets LOG_LEVEL=DEBUG (e.g. via -v/--verbose), enable console logging.
    setup_logging(log_file="run.log", console=(cfg.log_level.upper() == "DEBUG"), log_level=cfg.log_level)
    require_keys(cfg)

    try:
        df = load_df(cfg.input_csv)
    except FileNotFoundError:
        print(f"Error: The file '{cfg.input_csv}' was not found.")
        return

    cols = ensure_output_columns(df)
    url_col = cols[0]
    lim = Limiters.from_settings(cfg)

    # Build pending list with NA-safe emptiness check
    pending_rows: list[tuple[int, pd.Series]] = []
    for idx, row in df.iterrows():
        val = row.get(url_col, "")
        existing = "" if pd.isna(val) else str(val).strip()
        if existing == "" or existing.lower() in NULLISH:
            pending_rows.append((idx, row))

    print(f"Input rows: {len(df)}; pending: {len(pending_rows)}; output col: {url_col}")
    if not pending_rows:
        print("Nothing to do — output already populated.")
        return

    results: Dict[int, Tuple[str, str, str]] = {}
    in_flight: set[asyncio.Task[Any]] = set()
    pbar = tqdm(total=len(pending_rows), desc="Finding staff directories")
    completed_since_checkpoint = 0

    async def spawn(idx: int, row: pd.Series):
        return asyncio.create_task(_worker(idx, row, cols, cfg, lim, results))

    try:
        it = iter(pending_rows)
        # prime pool
        for _ in range(min(cfg.max_concurrent_schools, len(pending_rows))):
            i, r = next(it)
            in_flight.add(await spawn(i, r))

        while in_flight:
            done, in_flight = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
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
        print("\nInterrupted. Partial results saved.")


def entrypoint():
    """CLI entry point."""
    args = parse_args()
    apply_args_to_env(args)
    asyncio.run(main_async())


if __name__ == "__main__":
    entrypoint()
