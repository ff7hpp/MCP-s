"""Find currently mounted Google Drive for Desktop folders on Windows."""

import string
import sys
from pathlib import Path


def candidate_roots(home: Path | None = None, drives: list[Path] | None = None) -> list[Path]:
    """Return existing likely roots; no drive letter or username is assumed."""
    home = home or Path.home()
    if drives is None:
        drives = (
            [Path(f"{letter}:\\") for letter in string.ascii_uppercase]
            if sys.platform == "win32"
            else [Path("/")]
        )
    parents = [home, *drives]
    candidates: list[Path] = []
    seen: set[str] = set()
    for parent in parents:
        for name in ("My Drive", "Google Drive"):
            path = parent / name
            try:
                if not path.is_dir():
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)
    return candidates


def select_root(candidates: list[Path], response: str | None = None) -> Path | None:
    """Choose a sole root or a user-selected existing directory."""
    if response is None:
        return candidates[0] if len(candidates) == 1 else None
    response = response.strip()
    if response.isdecimal() and 1 <= int(response) <= len(candidates):
        return candidates[int(response) - 1]
    path = Path(response).expanduser()
    if path.is_dir():
        return path.resolve()
    raise ValueError("Google Drive path is not an existing directory")
