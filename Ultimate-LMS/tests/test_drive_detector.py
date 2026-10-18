from pathlib import Path

import pytest

from app.drive.detector import candidate_roots, select_root


def test_unique_drive_root(tmp_path: Path) -> None:
    drive = tmp_path / "disk"
    expected = drive / "My Drive"
    expected.mkdir(parents=True)
    assert candidate_roots(home=tmp_path / "home", drives=[drive]) == [expected.resolve()]
    assert select_root([expected]) == expected


def test_multiple_roots_require_selection(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert select_root([first, second]) is None
    assert select_root([first, second], "2") == second


def test_missing_path_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not an existing directory"):
        select_root([], str(tmp_path / "missing"))
