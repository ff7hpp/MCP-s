from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from app.drive.comparator import Comparison
from app.services import university


def test_browser_failure_does_not_stop_remaining_downloads(monkeypatch, tmp_path: Path) -> None:
    @contextmanager
    def fake_context(*, accept_downloads: bool):
        assert accept_downloads
        yield object()

    calls = 0

    def fake_download(context, row, comparison):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PlaywrightError("Download timed out")
        return tmp_path / "second.pdf"

    monkeypatch.setattr(university, "authenticated_context", fake_context)
    monkeypatch.setattr(university, "download_file", fake_download)
    items = [
        university.SyncItem({"name": name}, Comparison("SWE431", name, "MISSING", tmp_path / name))
        for name in ("first.pdf", "second.pdf")
    ]

    result = university.execute_sync(items)

    assert result[0].error == "Download timed out"
    assert result[1].downloaded_to == tmp_path / "second.pdf"
    assert calls == 2
