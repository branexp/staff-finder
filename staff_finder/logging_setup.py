"""Logging configuration for Staff Finder."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: str = "run.log", console: bool = False, log_level: str = "INFO") -> None:
    """Configure logging with optional file and console output.
    
    Args:
        log_file: Path to the log file.
        console: Whether to also log to console.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    
    # Parse log level
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)
