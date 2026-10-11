"""Download to local temporary storage, validate, then install without overwrite."""

import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import BrowserContext

from app.config import LMS_URL, PROJECT_ROOT
from app.drive.comparator import Comparison, normalized_name, size_matches

DOWNLOADS = PROJECT_ROOT / "downloads"
ALLOWED_PATH = "/web/Uzem/Ogrenci/Dersler/DersKaynaklari"


def _safe_remote_links(row: dict[str, object]) -> tuple[str, str]:
    resource = urlparse(str(row["resource_url"]))
    download = urlparse(str(row["download_url"]))
    expected_host = urlparse(LMS_URL).netloc
    if any(
        p.scheme != "https" or p.netloc != expected_host or p.path != ALLOWED_PATH
        for p in (resource, download)
    ):
        raise ValueError("DOWNLOAD_LINK_INVALID: unexpected destination")
    resource_query = parse_qs(resource.query)
    query = parse_qs(download.query)
    if (
        resource_query.get("Action") != ["Details"]
        or query.get("Action") != ["Details"]
        or any(resource_query.get(key) != query.get(key) for key in ("SID", "CRID"))
        or any(
            len(query.get(key, [])) != 1 or not query[key][0].isdigit()
            for key in ("SID", "CRID", "DownloadFile")
        )
        or query["DownloadFile"] != [str(row["remote_id"])]
    ):
        raise ValueError("DOWNLOAD_LINK_INVALID: identifiers differ")
    return str(row["resource_url"]), str(row["download_url"])


def _destination(comparison: Comparison) -> Path:
    target = comparison.target
    if comparison.status == "UPDATED" or target.exists():
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        candidate = target.with_name(f"{target.stem}_updated_{stamp}{target.suffix}")
        number = 2
        while candidate.exists():
            candidate = target.with_name(f"{target.stem}_updated_{stamp}_{number}{target.suffix}")
            number += 1
        return candidate
    return target


def install_download(source: Path, comparison: Comparison, expected_size: str) -> Path:
    """Validate local temp file and atomically rename a sibling into Drive on Windows."""
    if sys.platform != "win32":
        raise RuntimeError("SAFE_INSTALL_UNSUPPORTED: Windows-only atomic no-overwrite rename")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("DOWNLOAD_FAILED: file empty or absent")
    if size_matches(expected_size, source.stat().st_size) is False:
        raise ValueError("DOWNLOAD_FAILED: file size differs from LMS metadata")
    target = _destination(comparison)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, staged_name = tempfile.mkstemp(prefix=".lms-", suffix=".part", dir=target.parent)
    os.close(handle)
    staged = Path(staged_name)
    try:
        with source.open("rb") as incoming, staged.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if staged.stat().st_size != source.stat().st_size:
            raise ValueError("DOWNLOAD_FAILED: staging copy size differs")
        if target.exists():
            raise FileExistsError(f"FILE_EXISTS: {target}")
        os.rename(staged, target)
    finally:
        staged.unlink(missing_ok=True)
    return target


def download_file(context: BrowserContext, row: dict[str, object], comparison: Comparison) -> Path:
    resource_url, download_url = _safe_remote_links(row)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(resource_url, wait_until="domcontentloaded", timeout=30000)
    links = page.locator('a[title="Download File"]').filter(
        has=page.locator("i", has_text="download")
    )
    link = next((item for item in links.all() if item.get_attribute("href") == download_url), None)
    if link is None:
        raise RuntimeError("DOWNLOAD_LINK_NOT_FOUND")
    with page.expect_download(timeout=60000) as pending:
        link.click()
    download = pending.value
    if normalized_name(download.suggested_filename) != normalized_name(str(row["name"])):
        raise ValueError("DOWNLOAD_FAILED: suggested filename differs")
    with tempfile.TemporaryDirectory(dir=DOWNLOADS) as temporary:
        local_temp = Path(temporary) / "download.part"
        download.save_as(local_temp)
        return install_download(local_temp, comparison, str(row["size"]))
