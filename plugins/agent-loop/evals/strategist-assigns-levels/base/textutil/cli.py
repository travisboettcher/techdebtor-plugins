"""python3 -m textutil.cli: page titles on stdin, one HTML link per title on stdout."""

import sys

from textutil.index import dump_index
from textutil.links import render_links


def main() -> None:
    titles = [line.strip() for line in sys.stdin if line.strip()]
    print("\n".join(render_links(dump_index(titles))))


if __name__ == "__main__":
    main()
