from pathlib import Path

import pytest

from app.drive.comparator import Comparison
from app.drive.sync import install_download


def test_install_and_version_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "temp.pdf"
    source.write_bytes(b"x" * 1024)
    target = tmp_path / "Drive" / "Lecture1.pdf"
    comparison = Comparison("SWE431", "Lecture1.pdf", "MISSING", target)
    assert install_download(source, comparison, "1.00 KB") == target
    assert target.read_bytes() == source.read_bytes()
    updated = Comparison("SWE431", "Lecture1.pdf", "UPDATED", target, target)
    version = install_download(source, updated, "1.00 KB")
    assert version != target
    assert "_updated_" in version.name
    assert target.read_bytes() == source.read_bytes()


def test_reject_empty_and_wrong_size(tmp_path: Path) -> None:
    source = tmp_path / "temp.pdf"
    comparison = Comparison(
        "SWE431", "Lecture1.pdf", "MISSING", tmp_path / "Drive" / "Lecture1.pdf"
    )
    source.write_bytes(b"")
    with pytest.raises(ValueError, match="file empty"):
        install_download(source, comparison, "1.00 KB")
    source.write_bytes(b"x" * 500)
    with pytest.raises(ValueError, match="file size differs"):
        install_download(source, comparison, "1.00 KB")
