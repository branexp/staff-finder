"""Query planning for school staff directory searches."""

import re
from typing import List
from .models import School  # type: ignore
from .config import Settings  # type: ignore


def build_queries(cfg: Settings, s: School) -> List[str]:
    """Return up to cfg.max_queries_per_school simple, high-signal queries."""
    where = " ".join([p for p in (s.city, s.state) if p])
    q_school = f'"{s.name}"' if s.name else ""
    q_district = f'"{s.district}"' if s.district else ""

    candidates = [
        f'{q_school} "staff directory" {where}'.strip(),
        f'{q_school} ("faculty & staff" OR "faculty and staff" OR "staff") {where}'.strip(),
        f'{q_school} ("our staff" OR "staff list" OR "faculty directory" OR "directory") {where}'.strip(),
    ]
    if s.district:
        candidates.append(f'{q_district} ("staff directory" OR "directory") {q_school} {where}'.strip())

    seen, out = set(), []
    for q in candidates:
        q = re.sub(r"\s+", " ", q).strip()
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
        if len(out) >= cfg.max_queries_per_school:
            break
    return out
