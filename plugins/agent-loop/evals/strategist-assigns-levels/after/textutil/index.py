"""Build the site index: one JSON line per page."""

import json

from textutil.slug import slugify


def dump_index(titles: list[str]) -> str:
    """One JSON object per title, one per line: {"title": ..., "url": "/<slug>/"}."""
    return "\n".join(json.dumps({"title": t, "url": f"/{slugify(t)}/"}) for t in titles)
