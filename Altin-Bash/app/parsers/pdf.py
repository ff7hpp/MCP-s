"""PDF text extraction; image-only pages need external OCR."""

from pathlib import Path

from pypdf import PdfReader


def extract(path: Path, max_chars: int) -> str:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("DOCUMENT_ENCRYPTED: PDF requires a password")
    chunks: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        if text:
            chunks.append(text[: max_chars - total])
            total += len(chunks[-1])
        if total >= max_chars:
            break
    return "\n".join(chunks)
