"""Shortlist utilities for candidate URL selection."""



def round_robin_union(per_query: list[list[dict]], limit: int) -> list[dict]:
    """Interleave lists to keep variety; stop at limit."""
    out: list[dict] = []
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
