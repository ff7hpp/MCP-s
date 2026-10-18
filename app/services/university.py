"""Drive comparison and sequential sync orchestration."""

from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from app.config import LMS_URL, Config, load_config
from app.drive.comparator import Comparison, compare_file, get_drive_index
from app.drive.sync import download_file, transfer_file
from app.errors import ActionableError
from app.lms.auth import is_authenticated
from app.lms.browser import authenticated_context, authenticated_uzem_context
from app.services.scanner import ScanResult, scan_all, scan_one
from app.storage.database import latest_files
from app.storage.state import serialized


@dataclass
class SyncItem:
    row: dict[str, object]
    comparison: Comparison
    downloaded_to: Path | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        from app.drive.cloud import verification_status

        return {
            "course_code": self.comparison.course_code,
            "filename": self.comparison.filename,
            "status": self.comparison.status,
            "existing": str(self.comparison.existing) if self.comparison.existing else None,
            "target": str(self.comparison.target),
            "reason": self.comparison.reason,
            "downloaded_to": str(self.downloaded_to) if self.downloaded_to else None,
            "error": self.error,
            "source": self.comparison.source,
            "scanned_at": self.row.get("scanned_at"),
            "semester": self.row.get("semester"),
            "configured_term": self.comparison.term,
            **verification_status(
                self.row, self.downloaded_to or self.comparison.existing, load_config()
            ),
        }


@serialized
def prepare_sync(
    course_code: str | None = None, *, force_refresh: bool = False
) -> tuple[list[SyncItem], list[ScanResult]]:
    config: Config = load_config()
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    results = [scan_one(course_code)] if course_code else scan_all()
    if not course_code and not any(result.snapshot is not None for result in results):
        raise ActionableError(
            "LMS_SCAN_INCOMPLETE: no course scan succeeded; stored files may be stale"
        )
    failed = {result.code for result in results if result.error}
    failed.update(
        result.code
        for result in results
        if result.snapshot
        and any(
            key.split(":")[0] in {"files", "resources"} for key in result.snapshot.section_errors
        )
    )
    successful = {result.code for result in results if result.snapshot is not None}
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
        and str(row["course_code"]) in successful
    ]
    index = get_drive_index(
        config.drive_root,
        {str(row["course_code"]) for row in selected_rows},
        source="LMS",
        force_refresh=force_refresh,
        term=config.term,
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


@serialized
def execute_sync(
    items: list[SyncItem], *, source: str = "LMS", verify_content: bool = False
) -> list[SyncItem]:
    for item in items:
        item.error = None
        item.downloaded_to = None
    eligible = [
        item
        for item in items
        if item.comparison.status in {"MISSING", "NEW", "UPDATED"} or verify_content
    ]
    if not eligible:
        return items
    context_factory = authenticated_uzem_context if source == "UZEM" else authenticated_context
    with context_factory(accept_downloads=True) as context:
        if source == "UZEM":
            from app.uzem import portal

            portal._open(context.new_page(), portal.UZEM_URL)
        else:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
            if not is_authenticated(page):
                raise ActionableError(
                    "SESSION_EXPIRED: run `python -m app.cli login` and sign in manually"
                )
        for item in eligible:
            try:
                if item.comparison.sync_key:
                    item.comparison = compare_file(item.row, load_config(), source=source)
                    if not verify_content and item.comparison.status not in {
                        "MISSING",
                        "NEW",
                        "UPDATED",
                    }:
                        continue
                item.downloaded_to = (
                    transfer_file(context, item.row, item.comparison, source="UZEM")
                    if source == "UZEM"
                    else download_file(context, item.row, item.comparison)
                )
                if item.comparison.sync_key:
                    item.comparison = compare_file(item.row, load_config(), source=source)
            except (RuntimeError, ValueError, OSError, PlaywrightError, HTTPException) as exc:
                item.error = str(exc).splitlines()[0][:300]
    return items
