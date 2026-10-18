"""UTF-8 plain text and Markdown."""

from pathlib import Path


def extract(path: Path, max_chars: int) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read(max_chars)
