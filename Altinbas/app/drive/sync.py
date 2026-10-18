"""Download to local temporary storage, validate, then install without overwrite."""

import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from playwright.sync_api import BrowserContext

from app.config import LMS_URL, PROJECT_ROOT, require_current_term
from app.drive.comparator import Comparison, normalized_name, size_matches
from app.drive.comparator import validate_drive_path as validate_destination
from app.drive.records import get_record, record_install, record_pending
from app.lms.readonly import request_allowed
from app.storage.state import file_hash, serialized

DOWNLOADS = PROJECT_ROOT / "downloads"
ALLOWED_PATH = "/web/Uzem/Ogrenci/Dersler/DersKaynaklari"
MAX_BYTES = 25 * 1024 * 1024
TRANSFER_SECONDS = 120
EXTENSIONS = {
    ".pdf",
    ".pptx",
    ".docx",
    ".xlsx",
    ".txt",
    ".md",
    ".csv",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".doc",
    ".ppt",
    ".xls",
}


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
    if comparison.sync_key:
        return target.with_name(
            f"{target.stem}_rev_{comparison.remote_revision[:12]}{target.suffix}"
        )
    if comparison.status == "UPDATED" or target.exists():
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        candidate = target.with_name(f"{target.stem}_updated_{stamp}{target.suffix}")
        number = 2
        while candidate.exists():
            candidate = target.with_name(f"{target.stem}_updated_{stamp}_{number}{target.suffix}")
            number += 1
        return candidate
    return target


@serialized
def install_download(source: Path, comparison: Comparison, expected_size: str) -> Path:
    """Validate local temp file and atomically rename a sibling into Drive on Windows."""
    if sys.platform != "win32":
        raise RuntimeError("SAFE_INSTALL_UNSUPPORTED: Windows-only atomic no-overwrite rename")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("DOWNLOAD_FAILED: file empty or absent")
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("DOWNLOAD_TOO_LARGE")
    if size_matches(expected_size, source.stat().st_size) is False:
        raise ValueError("DOWNLOAD_FAILED: file size differs from LMS metadata")
    target = _destination(comparison)
    if comparison.drive_root:
        validate_destination(target, comparison.drive_root)
    if comparison.sync_key:
        previous = get_record(comparison.sync_key)
        if previous and previous.get("status") == "pending" and previous.get("staged"):
            abandoned = Path(previous["staged"])
            if (
                abandoned.parent == target.parent
                and abandoned.name.startswith(f".lms-{comparison.sync_key[:12]}-")
                and abandoned.suffix == ".part"
            ):
                if comparison.drive_root:
                    validate_destination(abandoned, comparison.drive_root)
                abandoned.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if comparison.drive_root:
        validate_destination(target, comparison.drive_root)
    if target.exists() and comparison.sync_key and file_hash(source) == file_hash(target):
        record_install(
            comparison.sync_key,
            comparison.remote_revision,
            target,
            metadata=comparison.receipt_metadata(),
        )
        return target
    if target.exists() and comparison.sync_key:
        target = target.with_name(f"{target.stem}_{file_hash(source)[:12]}{target.suffix}")
        if target.exists() and file_hash(source) == file_hash(target):
            record_install(
                comparison.sync_key,
                comparison.remote_revision,
                target,
                metadata=comparison.receipt_metadata(),
            )
            return target
    prefix = f".lms-{comparison.sync_key[:12]}-" if comparison.sync_key else ".lms-"
    handle, staged_name = tempfile.mkstemp(prefix=prefix, suffix=".part", dir=target.parent)
    os.close(handle)
    staged = Path(staged_name)
    try:
        if comparison.sync_key:
            record_pending(
                comparison.sync_key,
                comparison.remote_revision,
                target,
                source,
                staged,
                metadata=comparison.receipt_metadata(),
            )
        with source.open("rb") as incoming, staged.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if staged.stat().st_size != source.stat().st_size or file_hash(staged) != file_hash(source):
            raise ValueError("DOWNLOAD_FAILED: staging copy integrity differs")
        if target.exists():
            raise FileExistsError(f"FILE_EXISTS: {target}")
        os.rename(staged, target)
        if comparison.sync_key:
            record_install(
                comparison.sync_key,
                comparison.remote_revision,
                target,
                metadata=comparison.receipt_metadata(),
            )
    finally:
        staged.unlink(missing_ok=True)
    return target


def download_file(context: BrowserContext, row: dict[str, object], comparison: Comparison) -> Path:
    _safe_remote_links(row)
    return transfer_file(context, row, comparison, source="LMS")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def validate_download_url(url: str, source: str) -> None:
    parsed = urlparse(url)
    host = "uzem.altinbas.edu.tr" if source == "UZEM" else urlparse(LMS_URL).hostname
    paths = (
        parsed.path == "/mod/resource/view.php" or parsed.path.startswith("/pluginfile.php/")
        if source == "UZEM"
        else parsed.path == ALLOWED_PATH
    )
    if parsed.scheme != "https" or parsed.netloc != host or not paths:
        raise ValueError("DOWNLOAD_REDIRECT_REJECTED")
    if not request_allowed("GET", url, navigation=True):
        raise ValueError("DOWNLOAD_ACTION_REJECTED")
    query = parse_qs(parsed.query)
    if any(key.casefold() in {"sesskey", "delete", "submit", "markread"} for key in query):
        raise ValueError("DOWNLOAD_ACTION_REJECTED")


def validate_content(path: Path, filename: str, content_type: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS or filename != Path(filename).name or "\\" in filename:
        raise ValueError("DOWNLOAD_FILE_TYPE_REJECTED")
    with path.open("rb") as stream:
        head = stream.read(1024)
    if content_type.lower().split(";")[0] in {
        "text/html",
        "application/xhtml+xml",
    } or head.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("DOWNLOAD_HTML_REJECTED: session may have expired")
    if suffix == ".pdf" and b"%PDF-" not in head:
        raise ValueError("DOWNLOAD_SIGNATURE_INVALID")
    if suffix in {".docx", ".pptx", ".xlsx", ".zip"}:
        if not zipfile.is_zipfile(path):
            raise ValueError("DOWNLOAD_SIGNATURE_INVALID")
        with zipfile.ZipFile(path) as archive:
            prefix = {".docx": "word/", ".pptx": "ppt/", ".xlsx": "xl/"}.get(suffix)
            if prefix and not any(name.startswith(prefix) for name in archive.namelist()):
                raise ValueError("DOWNLOAD_OFFICE_TYPE_MISMATCH")
    if suffix in {".doc", ".ppt", ".xls"} and not head.startswith(bytes.fromhex("d0cf11e0a1b11e1")):
        raise ValueError("DOWNLOAD_SIGNATURE_INVALID")
    if suffix == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("DOWNLOAD_SIGNATURE_INVALID")
    if suffix in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise ValueError("DOWNLOAD_SIGNATURE_INVALID")


def transfer_file(
    context: BrowserContext, row: dict, comparison: Comparison, *, source: str
) -> Path:
    """Stream bounded GETs; authenticate only in memory; validate every redirect before sending."""
    from app.config import load_config
    from app.drive.comparator import _course_dirs, build_drive_index, safe_component

    config = load_config()
    require_current_term(row.get("semester"), config.term)
    deadline = time.monotonic() + TRANSFER_SECONDS
    if comparison.drive_root and not _course_dirs(
        comparison.drive_root, comparison.course_code, term=config.term
    ):
        raise ValueError(
            "COURSE_FOLDER_MISSING: sync requires an existing University course folder"
        )
    url = str(row["download_url"])
    opener = build_opener(NoRedirect())
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DOWNLOADS) as temporary:
        local_temp = Path(temporary) / "download.part"
        retries = 0
        for _ in range(6):
            if time.monotonic() >= deadline:
                raise ValueError("DOWNLOAD_DEADLINE_EXCEEDED: retry sync; existing files retained")
            validate_download_url(url, source)
            if source == "LMS":
                _safe_remote_links({**row, "download_url": url})
            # Cookie values remain in memory and the existing protected browser profile only.
            cookies = "; ".join(
                f"{cookie['name']}={cookie['value']}" for cookie in context.cookies([url])
            )
            request = Request(url, headers={"Cookie": cookies, "Accept-Encoding": "identity"})
            try:
                response = opener.open(
                    request, timeout=min(30, max(0.1, deadline - time.monotonic()))
                )
            except HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and retries < 2:
                    exc.close()
                    time.sleep(0.25 * (2**retries))
                    retries += 1
                    continue
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("Location")
                    exc.close()
                    if not location:
                        raise ValueError("DOWNLOAD_REDIRECT_INVALID") from None
                    url = urljoin(url, location)
                    continue
                raise RuntimeError(f"DOWNLOAD_HTTP_{exc.code}") from None
            except (URLError, TimeoutError) as exc:
                if retries < 2:
                    time.sleep(0.25 * (2**retries))
                    retries += 1
                    continue
                raise RuntimeError(
                    "DOWNLOAD_NETWORK_FAILED: retry sync; installed files are retained"
                ) from exc
            with response:
                if response.status != 200:
                    raise ValueError("DOWNLOAD_RESPONSE_INVALID")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_BYTES:
                    raise ValueError("DOWNLOAD_TOO_LARGE")
                disposition = Message()
                disposition["Content-Disposition"] = response.headers.get("Content-Disposition", "")
                suggested = disposition.get_filename()
                if suggested and normalized_name(suggested) != normalized_name(str(row["name"])):
                    raise ValueError("DOWNLOAD_FILENAME_MISMATCH")
                with local_temp.open("wb") as handle:
                    remaining = MAX_BYTES + 1
                    while chunk := response.read(min(65536, remaining)):
                        if time.monotonic() >= deadline:
                            raise ValueError("DOWNLOAD_DEADLINE_EXCEEDED: transfer budget expired")
                        handle.write(chunk)
                        remaining -= len(chunk)
                        if remaining == 0:
                            raise ValueError("DOWNLOAD_TOO_LARGE")
                if time.monotonic() >= deadline:
                    raise ValueError("DOWNLOAD_DEADLINE_EXCEEDED: transfer budget expired")
                validate_content(
                    local_temp, str(row["name"]), response.headers.get("Content-Type", "")
                )
            candidates = [comparison.existing] if comparison.existing else []
            if comparison.drive_root:
                index = build_drive_index(
                    comparison.drive_root, {comparison.course_code}, source=source, term=config.term
                )
                candidates.extend(
                    index.get(
                        (
                            comparison.course_code.casefold(),
                            normalized_name(safe_component(str(row["name"]))),
                        ),
                        [],
                    )
                )
            for candidate in sorted(set(candidates), key=lambda path: (len(path.parts), str(path))):
                if candidate.is_file():
                    if comparison.drive_root:
                        validate_destination(candidate, comparison.drive_root)
                    if local_temp.stat().st_size == candidate.stat().st_size and file_hash(
                        local_temp
                    ) == file_hash(candidate):
                        desired_folder = (
                            next(
                                (
                                    folder
                                    for folder in _course_dirs(
                                        comparison.drive_root,
                                        comparison.course_code,
                                        term=config.term,
                                    )
                                    if comparison.target.is_relative_to(folder)
                                ),
                                None,
                            )
                            if comparison.drive_root
                            else None
                        )
                        if desired_folder and not candidate.is_relative_to(desired_folder):
                            destination = comparison.target
                            validate_destination(destination, comparison.drive_root)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            validate_destination(destination, comparison.drive_root)
                            if destination.exists():
                                if file_hash(destination) == file_hash(candidate):
                                    candidate = destination
                                else:
                                    raise ValueError(
                                        "RELOCATION_CONFLICT: existing target differs; original retained"
                                    )
                            else:
                                if sys.platform != "win32":
                                    raise RuntimeError(
                                        "SAFE_INSTALL_UNSUPPORTED: Windows-only no-overwrite relocation"
                                    )
                                record_pending(
                                    comparison.sync_key,
                                    comparison.remote_revision,
                                    destination,
                                    candidate,
                                    metadata=comparison.receipt_metadata(),
                                )
                                os.rename(candidate, destination)
                                candidate = destination
                        record_install(
                            comparison.sync_key,
                            comparison.remote_revision,
                            candidate,
                            metadata=comparison.receipt_metadata(),
                        )
                        return candidate
            return install_download(local_temp, comparison, str(row["size"]))
        raise ValueError("DOWNLOAD_ATTEMPT_LIMIT")
