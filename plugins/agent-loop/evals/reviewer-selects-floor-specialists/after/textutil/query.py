"""Parse query strings from request URLs."""

import re

_PAIR = re.compile(r"([^=&]+)=([^&]*)")


def parse_query(query: str) -> dict[str, str]:
    """Parse "a=1&b=2" into {"a": "1", "b": "2"}; raise ValueError on a pair without "="."""
    result = {}
    for part in query.split("&"):
        if not part:
            continue
        match = _PAIR.fullmatch(part)
        if match is None:
            raise ValueError(f"not a key=value pair: {part!r}")
        result[match.group(1)] = match.group(2)
    return result
