"""Compare and safely copy Moodle resource files from old UZEM to Drive."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError

from app.config import Config, load_config
from app.drive.comparator import Comparison, compare_file
from app.drive.sync import install_download
from app.lms.browser import authenticated_uzem_context
from app.uzem import portal


@dataclass
class UzemSyncItem:
    row: dict[str, object]
    comparison: Comparison
    downloaded_to: Path | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "course_code": self.comparison.course_code,
            "filename": self.comparison.filename,
            "status": self.comparison.status,
            "existing": str(self.comparison.existing) if self.comparison.existing else None,
            "target": str(self.comparison.target),
            "reason": self.comparison.reason,
            "downloaded_to": str(self.downloaded_to) if self.downloaded_to else None,
            "error": self.error,
        }


def prepare_sync(course_code: str | None = None) -> list[UzemSyncItem]:
    config: Config = load_config()
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    files = portal.scan_all()["files"]
    items = []
    for row in files:
        if course_code and str(row["course_code"]).casefold() != course_code.casefold():
            continue
        items.append(UzemSyncItem(row, compare_file(row, config, source="UZEM")))
    return items


def execute_sync(items: list[UzemSyncItem]) -> list[UzemSyncItem]:
    eligible = [item for item in items if item.comparison.status in {"MISSING", "NEW", "UPDATED"}]
    if not eligible:
        return items
    with authenticated_uzem_context(accept_downloads=True) as context:
        page = context.new_page()
        portal._open(page, portal.UZEM_URL)
        for item in eligible:
            try:
                url = str(item.row["download_url"])
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname != portal.HOST:
                    raise ValueError("UZEM_DOWNLOAD_URL_REJECTED")
                with page.expect_download(timeout=60000) as pending:
                    page.evaluate("url => window.location.assign(url)", url)
                download = pending.value
                with TemporaryDirectory(
                    prefix="uzem-download-", dir=portal.UZEM_PROFILE_PATH
                ) as temp:
                    temporary = Path(temp) / "download.part"
                    download.save_as(temporary)
                    if download.suggested_filename.casefold() != str(item.row["name"]).casefold():
                        raise ValueError("UZEM_FILENAME_MISMATCH")
                    item.downloaded_to = install_download(
                        temporary, item.comparison, str(item.row["size"])
                    )
            except (RuntimeError, ValueError, OSError, PlaywrightError) as exc:
                item.error = str(exc).splitlines()[0][:300]
    return items
