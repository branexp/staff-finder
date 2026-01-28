"""Shortlist utilities for candidate URL selection."""

from typing import Dict, List


def round_robin_union(per_query: List[List[Dict]], limit: int) -> List[Dict]:
    """Interleave lists to keep variety; stop at limit."""
    out: List[Dict] = []
    seen = set()
    i = 0
    while len(out) < limit:
        added = False
        for lst in per_query:
            if i < len(lst):
                item = lst[i]
                url = (item.get("url") or "").strip().lower()
                if url and url not in seen:
                    out.append(item)
                    seen.add(url)
                    if len(out) >= limit:
                        break
                added = True
        if not added:
            break
        i += 1
    return out
