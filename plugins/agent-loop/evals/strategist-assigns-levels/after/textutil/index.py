"""Build the site index: one JSON line per page."""

import json

from textutil.slug import slugify


def dump_index(titles: list[str]) -> str:
    """One JSON object per title, one per line: {"title": ..., "url": "/<slug>/"}.

    A slug already taken by an earlier title gets "-2", "-3", ... appended.
    """
    seen: dict[str, int] = {}
    lines = []
    for title in titles:
        slug = slugify(title)
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        lines.append(json.dumps({"title": title, "url": f"/{slug}/"}))
    return "\n".join(lines)
