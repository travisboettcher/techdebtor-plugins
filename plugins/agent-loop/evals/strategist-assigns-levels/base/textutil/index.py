"""Build the site index: one JSON line per page."""

import json

from textutil.slug import slugify


def dump_index(titles: list[str]) -> str:
    """One JSON object per title, one per line: {"title": ..., "slug": ...}."""
    return "\n".join(json.dumps({"title": t, "slug": slugify(t)}) for t in titles)
