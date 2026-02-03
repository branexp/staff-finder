"""Data models for Staff Finder."""

from dataclasses import dataclass

import pandas as pd  # type: ignore


@dataclass
class School:
    """Represents a school with location information."""
    name: str
    district: str
    county: str
    city: str
    state: str


@dataclass
class SelectionResult:
    """Represents the result of URL selection with confidence and reasoning."""
    url: str
    confidence: str | None = None
    reasoning: str = ""


def map_headers(row: "pd.Series") -> School:
    """Map CSV row headers to School dataclass with flexible column matching."""
    # Flexible header mapping (case-insensitive)
    lookup = {k.lower(): ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
    
    def get(*keys: str) -> str:
        for k in keys:
            v = lookup.get(k.lower())
            if v:
                return v
        return ""
    
    return School(
        name=get("school_name", "name", "school"),
        district=get("district_name", "district"),
        county=get("county_name", "county"),
        city=get("city"),
        state=get("state")
    )
