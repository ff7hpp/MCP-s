"""Drive comparison and sequential sync orchestration."""

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from app.config import Config, load_config
from app.drive.comparator import Comparison, compare_file, get_drive_index
from app.drive.sync import download_file
from app.lms.browser import authenticated_context
from app.services.scanner import ScanResult, scan_all, scan_one
from app.storage.database import latest_files


@dataclass
class SyncItem:
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


def prepare_sync(
    course_code: str | None = None, *, force_refresh: bool = False
) -> tuple[list[SyncItem], list[ScanResult]]:
    config: Config = load_config()
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    results = [scan_one(course_code)] if course_code else scan_all()
    failed = {result.code for result in results if result.error}
    if course_code and failed:
        raise RuntimeError(results[0].error or "SCAN_FAILED")
    recent = {
        (change["course"], change["name"]): change["status"]
        for result in results
        for change in result.changes
        if change["type"] == "file"
    }
    rows = latest_files()
    selected_rows = [
        row
        for row in rows
        if (course_code is None or str(row["course_code"]).casefold() == course_code.casefold())
        and str(row["course_code"]) not in failed
    ]
    index = get_drive_index(
        config.drive_root,
        {str(row["course_code"]) for row in selected_rows},
        source="LMS",
        force_refresh=force_refresh,
    )
    items = [
        SyncItem(
            row,
            compare_file(
                row,
                config,
                recent.get((str(row["course_code"]), str(row["name"]))),
                source="LMS",
                drive_index=index,
            ),
        )
        for row in selected_rows
    ]
    return items, results


def execute_sync(items: list[SyncItem]) -> list[SyncItem]:
    eligible = [item for item in items if item.comparison.status in {"MISSING", "NEW", "UPDATED"}]
    if not eligible:
        return items
    with authenticated_context(accept_downloads=True) as context:
        for item in eligible:
            try:
                item.downloaded_to = download_file(context, item.row, item.comparison)
            except (RuntimeError, ValueError, OSError, PlaywrightError) as exc:
                item.error = str(exc).splitlines()[0][:300]
    return items
