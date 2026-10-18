"""Conservative comparison of LMS metadata with local Drive files."""

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlparse

from app.config import Config, require_current_term
from app.drive.records import get_record, identity, revision
from app.errors import ActionableError
from app.storage.state import digest, file_hash

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)\s*$", re.IGNORECASE)
DriveFileIndex = dict[tuple[str, tuple[str, str]], list[Path]]
_DRIVE_INDEX_TTL_SECONDS = 15.0
_DRIVE_INDEX_CACHE: dict[tuple[str, str], tuple[float, set[str], DriveFileIndex]] = {}
_DRIVE_INDEX_LOCK = RLock()


@dataclass(frozen=True)
class Comparison:
    course_code: str
    filename: str
    status: str
    target: Path
    existing: Path | None = None
    reason: str = ""
    sync_key: str = ""
    remote_revision: str = ""
    drive_root: Path | None = None
    source: str = "LMS"
    term: str = ""

    def receipt_metadata(self) -> dict[str, str]:
        return {
            "course_code": self.course_code,
            "filename": self.filename,
            "term": self.term,
            "source": self.source,
        }


def validate_drive_path(target: Path, root: Path) -> None:
    university = root / "University"
    if not target.resolve().is_relative_to(university.resolve()):
        raise ValueError("DESTINATION_OUTSIDE_UNIVERSITY")
    current = target
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise ValueError("DESTINATION_LINK_REJECTED")
        if current.parent == current:
            raise ValueError("DESTINATION_OUTSIDE_DRIVE")
        current = current.parent


def safe_component(value: str) -> str:
    text = INVALID.sub("-", unicodedata.normalize("NFKC", value)).strip(" .")
    if len(text) > 100:
        suffix = Path(text).suffix[:20]
        token = "_" + digest(text)[:10]
        text = text[: 100 - len(suffix) - len(token)].rstrip(" .") + token + suffix
    if not text:
        text = "untitled"
    if text.split(".")[0].upper() in RESERVED:
        text = f"_{text}"
    return text


def normalized_name(value: str) -> tuple[str, str]:
    name = unicodedata.normalize("NFKC", value).casefold()
    suffix = Path(name).suffix
    stem = name[: -len(suffix)] if suffix else name
    return re.sub(r"[\s_-]+", "", stem), suffix


def size_matches(display: str, actual_bytes: int) -> bool | None:
    match = SIZE.fullmatch(display)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "B":
        return abs(actual_bytes - amount) <= 0.5
    power = {"KB": 1, "MB": 2, "GB": 3}[unit]
    decimals = len(match.group(1).partition(".")[2])
    for base in (1000, 1024):
        factor = base**power
        tolerance = 0.5 * 10 ** (-decimals) * factor
        if abs(actual_bytes - amount * factor) <= tolerance:
            return True
    return False


def course_target(
    config: Config,
    course_code: str,
    resource_title: str,
    resource_url: str,
    filename: str,
    *,
    source: str = "LMS",
) -> Path:
    if config.drive_root is None:
        raise ValueError("DRIVE_NOT_CONFIGURED")
    term = safe_component(config.term.replace("/", "-"))
    query = parse_qs(urlparse(resource_url).query)
    resource_id = (query.get("CRID") or query.get("id") or ["unknown"])[0]
    if not resource_id.isdigit():
        resource_id = "unknown"
    folder = f"{safe_component(resource_title)}__{resource_id}"
    existing = _course_dirs(config.drive_root, course_code, term=config.term)
    flat = [path for path in existing if path.parent == config.drive_root / "University"]
    choices = flat or existing
    if len(choices) > 1:
        raise ValueError("COURSE_FOLDER_AMBIGUOUS: choose a single existing course folder")
    base = (
        choices[0]
        if choices
        else config.drive_root / "University" / term / safe_component(course_code)
    )
    return base / safe_component(source) / "Resources" / folder / safe_component(filename)


def build_drive_index(
    root: Path, course_codes: set[str], *, source: str, term: str = Config.term
) -> DriveFileIndex:
    """Index matching files in one pass through the University folder tree."""
    university = root / "University"
    if (
        not course_codes
        or not university.is_dir()
        or university.is_symlink()
        or university.is_junction()
    ):
        return {}
    patterns = {
        code.casefold(): re.compile(rf"^{re.escape(code.casefold())}(?:$|[\s_-])")
        for code in course_codes
    }
    wanted_source = source.casefold()
    index: DriveFileIndex = {}
    for parent, dirs, files in os.walk(university, followlinks=False):
        dirs[:] = [
            name
            for name in dirs
            if not ((Path(parent) / name).is_symlink() or (Path(parent) / name).is_junction())
        ]
        relative = Path(parent).relative_to(university).parts
        course_key = None
        course_position = None
        for position, component in enumerate(relative):
            course_key = next(
                (code for code, pattern in patterns.items() if pattern.match(component.casefold())),
                None,
            )
            if course_key:
                course_position = position
                break
        if course_key is None or course_position is None:
            continue
        if course_position > 1 or (
            course_position == 1 and relative[0] != safe_component(term.replace("/", "-"))
        ):
            continue
        source_labels = {
            part.casefold()
            for part in relative[course_position + 1 :]
            if part.casefold() in {"lms", "uzem"}
        }
        if source_labels and wanted_source not in source_labels:
            continue
        for filename in files:
            path = Path(parent) / filename
            key = (course_key, normalized_name(filename))
            index.setdefault(key, []).append(path)
    return index


def _course_dirs(root: Path, course_code: str, *, term: str = Config.term) -> list[Path]:
    """Find course directories for the local document lookup service."""
    university = root / "University"
    if not university.is_dir() or university.is_symlink() or university.is_junction():
        return []
    wanted = re.compile(rf"^{re.escape(course_code.casefold())}(?:$|[\s_-])")
    matches = []
    for parent, dirs, _ in os.walk(university, followlinks=False):
        for directory in list(dirs):
            candidate = Path(parent) / directory
            if candidate.is_symlink() or candidate.is_junction():
                dirs.remove(directory)
            elif wanted.match(directory.casefold()):
                relative = candidate.relative_to(university).parts
                if len(relative) == 1 or (
                    len(relative) == 2 and relative[0] == safe_component(term.replace("/", "-"))
                ):
                    matches.append(candidate)
                dirs.remove(directory)
    return matches


def get_drive_index(
    root: Path,
    course_codes: set[str],
    *,
    source: str,
    force_refresh: bool = False,
    term: str = Config.term,
) -> DriveFileIndex:
    """Return a process-local index; refresh it every 15 seconds or before writes."""
    with _DRIVE_INDEX_LOCK:
        key = (str(root.resolve()).casefold(), source.casefold() + ":" + term)
        now = time.monotonic()
        cached = _DRIVE_INDEX_CACHE.get(key)
        if cached and not force_refresh and now - cached[0] < _DRIVE_INDEX_TTL_SECONDS:
            cached_at, indexed_codes, index = cached
            missing_codes = course_codes - indexed_codes
            if not missing_codes:
                return index
            added = build_drive_index(root, missing_codes, source=source, term=term)
            for filename_key, paths in added.items():
                index.setdefault(filename_key, []).extend(paths)
            indexed_codes.update(missing_codes)
            _DRIVE_INDEX_CACHE[key] = (cached_at, indexed_codes, index)
            return index

        indexed_codes = set(course_codes)
        if cached:
            indexed_codes.update(cached[1])
        index = build_drive_index(root, indexed_codes, source=source, term=term)
        _DRIVE_INDEX_CACHE[key] = (now, indexed_codes, index)
        return index


def compare_file(
    row: dict[str, object],
    config: Config,
    recent_status: str | None = None,
    *,
    source: str = "LMS",
    drive_index: DriveFileIndex | None = None,
) -> Comparison:
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    code = str(row["course_code"])
    name = str(row["name"])
    target = course_target(
        config,
        code,
        str(row["resource_title"]),
        str(row["resource_url"]),
        name,
        source=source,
    )
    key = identity(row, config, source)
    remote_revision = revision(row)

    def result(status, existing=None, reason=""):
        return Comparison(
            code,
            name,
            status,
            target,
            existing,
            reason,
            key,
            remote_revision,
            config.drive_root,
            source,
            config.term,
        )

    try:
        require_current_term(row.get("semester"), config.term)
    except ActionableError as exc:
        return result("UNKNOWN", reason=str(exc))
    receipt = get_record(key)
    if receipt:
        installed = Path(receipt["path"])
        try:
            validate_drive_path(installed, config.drive_root)
        except (ValueError, OSError):
            installed = None
        if installed is not None and receipt.get("status") == "pending" and not installed.exists():
            return result("UPDATED", reason="Interrupted transfer pending; safe retry required")
        if (
            installed is not None
            and installed.is_file()
            and installed.resolve().is_relative_to(config.drive_root.resolve())
        ):
            if receipt["revision"] != remote_revision:
                return result(
                    "UPDATED", installed, "Remote identity changed, including same-size replacement"
                )
            if installed.stat().st_size != receipt["size"]:
                return result("UPDATED", installed, "Local size differs from sync receipt")
            if file_hash(installed) == receipt["sha256"]:
                desired_folder = next(
                    (
                        folder
                        for folder in _course_dirs(config.drive_root, code, term=config.term)
                        if target.is_relative_to(folder)
                    ),
                    None,
                )
                if desired_folder and not installed.is_relative_to(desired_folder):
                    return result(
                        "UPDATED",
                        installed,
                        "Verified legacy file needs placement in existing course folder",
                    )
                return result(
                    "PRESENT",
                    installed,
                    "Term, remote revision and local SHA-256 verified; cloud unverified",
                )
            return result("UPDATED", installed, "Local content differs from sync receipt")
    wanted = normalized_name(safe_component(name))
    if drive_index is None:
        drive_index = build_drive_index(config.drive_root, {code}, source=source, term=config.term)
    candidates = drive_index.get((code.casefold(), wanted), [])
    if len(candidates) > 1:
        return result("UNKNOWN", reason="Multiple local filename matches")
    if candidates:
        existing = candidates[0]
        try:
            validate_drive_path(existing, config.drive_root)
            inside_drive = True
        except (OSError, ValueError):
            inside_drive = False
        if not inside_drive:
            return result("UNKNOWN", reason="Local match points outside Drive")
        try:
            match = size_matches(str(row["size"]), existing.stat().st_size)
        except OSError:
            match = None
        if match is True:
            if int(row["revision"]) > 1 or recent_status == "UPDATED":
                return result("UPDATED", existing, "Remote revision requires a verified receipt")
            return result("UNKNOWN", existing, "Name and size match; remote identity unverified")
        if match is None:
            return result("UNKNOWN", existing, "Local size could not be verified")
        if int(row["revision"]) > 1 or recent_status == "UPDATED":
            return result("UPDATED", existing, "Name matches; size changed")
        return result("UNKNOWN", existing, "Name matches; size differs")
    if int(row["revision"]) > 1 or recent_status == "UPDATED":
        status = "UPDATED"
    elif recent_status == "NEW":
        status = "NEW"
    else:
        status = "MISSING"
    return result(status)
