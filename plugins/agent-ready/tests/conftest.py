"""Helpers for building small synthetic repositories in tmp_path."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def write_tree(root: Path, files: dict) -> Path:
    """Write {relative path: str | bytes} under root and return root."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    return root


@pytest.fixture
def repo(tmp_path):
    def make(files: dict, name: str = "repo") -> Path:
        return write_tree(tmp_path / name, files)
    return make
