from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Error as PlaywrightError

from app.config import Config
from app.drive.comparator import Comparison
from app.services import university
from app.services.scanner import ScanResult


def test_browser_failure_does_not_stop_remaining_downloads(monkeypatch, tmp_path: Path) -> None:
    @contextmanager
    def fake_context(*, accept_downloads: bool):
        assert accept_downloads
        yield MagicMock()

    calls = 0

    def fake_download(context, row, comparison):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PlaywrightError("Download timed out")
        return tmp_path / "second.pdf"

    monkeypatch.setattr(university, "authenticated_context", fake_context)
    monkeypatch.setattr(university, "is_authenticated", lambda page: True)
    monkeypatch.setattr(university, "download_file", fake_download)
    items = [
        university.SyncItem({"name": name}, Comparison("SWE431", name, "MISSING", tmp_path / name))
        for name in ("first.pdf", "second.pdf")
    ]

    result = university.execute_sync(items)

    assert result[0].error == "Download timed out"
    assert result[1].downloaded_to == tmp_path / "second.pdf"
    assert calls == 2
    university.execute_sync([result[0]])
    assert result[0].error is None
    assert result[0].downloaded_to == tmp_path / "second.pdf"


def test_failed_live_scan_does_not_sync_stored_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        university, "load_config", lambda: Config(term="Fall 2026/2027", drive_root=tmp_path)
    )
    monkeypatch.setattr(
        university, "scan_all", lambda: [ScanResult("GLOBAL", None, [], "COURSE_DISCOVERY_FAILED")]
    )
    monkeypatch.setattr(
        university,
        "latest_files",
        lambda: pytest.fail("Stored files must not be used after failed live scan"),
    )

    with pytest.raises(RuntimeError, match="LMS_SCAN_INCOMPLETE"):
        university.prepare_sync()
