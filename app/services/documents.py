"""Locate and read only files under configured local Drive root."""

import os
from dataclasses import dataclass
from pathlib import Path

from app.config import load_config
from app.drive.comparator import _course_dirs, normalized_name
from app.parsers import docx, pdf, pptx, text

MAX_BYTES = 25 * 1024 * 1024
MAX_CHARS = 250_000
READERS = {
    ".pdf": pdf.extract,
    ".pptx": pptx.extract,
    ".docx": docx.extract,
    ".txt": text.extract,
    ".md": text.extract,
}


@dataclass(frozen=True)
class DocumentText:
    path: Path
    size_bytes: int
    text: str
    truncated: bool

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "text": self.text,
            "truncated": self.truncated,
        }


def find_file(course_code: str, filename: str) -> Path:
    config = load_config()
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError("DRIVE_UNAVAILABLE")
    if not course_code or not filename or "/" in filename or "\\" in filename:
        raise ValueError("FILE_NAME_INVALID")
    wanted = normalized_name(filename)
    matches: list[Path] = []
    for directory in _course_dirs(config.drive_root, course_code):
        for parent, _, files in os.walk(directory, followlinks=False):
            for name in files:
                if normalized_name(name) == wanted:
                    matches.append(Path(parent) / name)
    if not matches:
        raise FileNotFoundError(f"LOCAL_FILE_NOT_FOUND: {course_code}/{filename}")
    if len(matches) != 1:
        raise ValueError(f"LOCAL_FILE_AMBIGUOUS: {course_code}/{filename}")
    root = config.drive_root.resolve()
    resolved = matches[0].resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("FILE_OUTSIDE_DRIVE")
    return resolved


def read_document(course_code: str, filename: str, max_chars: int = MAX_CHARS) -> DocumentText:
    if not 1 <= max_chars <= MAX_CHARS:
        raise ValueError(f"TEXT_LIMIT_INVALID: choose 1..{MAX_CHARS}")
    path = find_file(course_code, filename)
    size = path.stat().st_size
    if size == 0:
        raise ValueError("DOCUMENT_EMPTY")
    if size > MAX_BYTES:
        raise ValueError(f"DOCUMENT_TOO_LARGE: limit {MAX_BYTES} bytes")
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"DOCUMENT_TYPE_UNSUPPORTED: {path.suffix}")
    extracted = reader(path, max_chars + 1)
    return DocumentText(path, size, extracted[:max_chars], len(extracted) > max_chars)
