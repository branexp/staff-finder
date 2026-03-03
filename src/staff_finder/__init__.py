"""Staff Finder - CLI tool for discovering staff directory URLs for K-12 schools."""

from .config import ConfigError, Settings, load_settings

__all__ = [
    "ConfigError",
    "Settings",
    "load_settings",
]
