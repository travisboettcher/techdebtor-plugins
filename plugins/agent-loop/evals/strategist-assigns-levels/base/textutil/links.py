"""Render the site index as HTML links."""

import html
import json


def render_links(index_text: str) -> list[str]:
    """One <a> element per index line, in order."""
    links = []
    for line in index_text.splitlines():
        if line.strip():
            entry = json.loads(line)
            links.append(f'<a href="/{entry["slug"]}/">{html.escape(entry["title"])}</a>')
    return links
