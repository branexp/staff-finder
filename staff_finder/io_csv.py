"""CSV input/output utilities."""

from typing import Tuple
import pandas as pd  # type: ignore


def load_df(path: str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame with flexible types."""
    # Keep types flexible; do not force str to avoid NA weirdness
    return pd.read_csv(path, dtype=object)


def ensure_output_columns(df: pd.DataFrame, preferred: str = "StaffDirectoryURL") -> Tuple[str, str, str]:
    """Ensure output columns exist and return their names.
    
    Returns:
        Tuple of (url_column, confidence_column, reasoning_column)
    """
    lower = {c.lower(): c for c in df.columns}
    
    # Find or create URL column
    url_col = None
    for alias in ("staffdirectoryurl", "staff_directory_url", "staff_directory_page", "staffdirectory", "directory_url"):
        if alias in lower:
            url_col = lower[alias]
            break
    
    if url_col is None:
        df[preferred] = pd.NA
        url_col = preferred
    
    # Ensure Confidence column
    if "Confidence" not in df.columns:
        df["Confidence"] = pd.NA
    
    # Ensure Reasoning column
    if "Reasoning" not in df.columns:
        df["Reasoning"] = pd.NA
    
    return url_col, "Confidence", "Reasoning"


def save_df(df: pd.DataFrame, path: str) -> None:
    """Save a DataFrame to CSV."""
    df.to_csv(path, index=False)
