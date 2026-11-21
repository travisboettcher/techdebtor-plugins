"""Turn titles into URL slugs."""

import re
import unicodedata


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by single hyphens."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words)
