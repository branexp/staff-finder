"""Staff Finder - Async CLI tool for discovering staff directory URLs for K-12 schools."""

from .processor import StaffFinder
from .jina_client import JinaSearchClient
from .openai_selector import OpenAISelector

__version__ = "0.1.0"
__all__ = ["StaffFinder", "JinaSearchClient", "OpenAISelector"]
