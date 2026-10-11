"""Conservative comparison of LMS metadata with local Drive files."""

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlparse

from app.config import Config

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
_DRIVE_INDEX_CACHE: dict[
    tuple[str, str], tuple[float, set[str], DriveFileIndex]
] = {}
_DRIVE_INDEX_LOCK = RLock()


@dataclass(frozen=True)
class Comparison:
    course_code: str
    filename: str
    status: str
    target: Path
    existing: Path | None = None
    reason: str = ""


def safe_component(value: str) -> str:
    text = INVALID.sub("-", unicodedata.normalize("NFKC", value)).strip(" .")[:100].rstrip(" .")
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
    return (
        config.drive_root
        / "University"
        / term
        / safe_component(course_code)
        / safe_component(source)
        / "Resources"
        / folder
        / safe_component(filename)
    )


def build_drive_index(root: Path, course_codes: set[str], *, source: str) -> DriveFileIndex:
    """Index matching files in one pass through the University folder tree."""
    university = root / "University"
    if not course_codes or not university.is_dir():
        return {}
    patterns = {
        code.casefold(): re.compile(rf"^{re.escape(code.casefold())}(?:$|[\s_-])")
        for code in course_codes
    }
    wanted_source = source.casefold()
    index: DriveFileIndex = {}
    for parent, dirs, files in os.walk(university, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
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


def _course_dirs(root: Path, course_code: str) -> list[Path]:
    """Find course directories for the local document lookup service."""
    university = root / "University"
    if not university.is_dir():
        return []
    wanted = re.compile(rf"^{re.escape(course_code.casefold())}(?:$|[\s_-])")
    matches = []
    for parent, dirs, _ in os.walk(university, followlinks=False):
        for directory in list(dirs):
            candidate = Path(parent) / directory
            if candidate.is_symlink():
                dirs.remove(directory)
            elif wanted.match(directory.casefold()):
                matches.append(candidate)
                dirs.remove(directory)
    return matches


def get_drive_index(
    root: Path,
    course_codes: set[str],
    *,
    source: str,
    force_refresh: bool = False,
) -> DriveFileIndex:
    """Return a process-local index; refresh it every 15 seconds or before writes."""
    with _DRIVE_INDEX_LOCK:
        key = (str(root.resolve()).casefold(), source.casefold())
        now = time.monotonic()
        cached = _DRIVE_INDEX_CACHE.get(key)
        if cached and not force_refresh and now - cached[0] < _DRIVE_INDEX_TTL_SECONDS:
            cached_at, indexed_codes, index = cached
            missing_codes = course_codes - indexed_codes
            if not missing_codes:
                return index
            added = build_drive_index(root, missing_codes, source=source)
            for filename_key, paths in added.items():
                index.setdefault(filename_key, []).extend(paths)
            indexed_codes.update(missing_codes)
            _DRIVE_INDEX_CACHE[key] = (cached_at, indexed_codes, index)
            return index

        indexed_codes = set(course_codes)
        if cached:
            indexed_codes.update(cached[1])
        index = build_drive_index(root, indexed_codes, source=source)
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
    wanted = normalized_name(name)
    if drive_index is None:
        drive_index = build_drive_index(config.drive_root, {code}, source=source)
    candidates = drive_index.get((code.casefold(), wanted), [])
    if len(candidates) > 1:
        return Comparison(code, name, "UNKNOWN", target, reason="Multiple local filename matches")
    if candidates:
        existing = candidates[0]
        try:
            inside_drive = existing.resolve().is_relative_to(config.drive_root.resolve())
        except OSError:
            inside_drive = False
        if not inside_drive:
            return Comparison(
                code, name, "UNKNOWN", target, reason="Local match points outside Drive"
            )
        try:
            match = size_matches(str(row["size"]), existing.stat().st_size)
        except OSError:
            match = None
        if match is True:
            return Comparison(code, name, "PRESENT", target, existing)
        if match is None:
            return Comparison(
                code, name, "UNKNOWN", target, existing, "Local size could not be verified"
            )
        if int(row["revision"]) > 1 or recent_status == "UPDATED":
            return Comparison(code, name, "UPDATED", target, existing, "Name matches; size changed")
        return Comparison(code, name, "UNKNOWN", target, existing, "Name matches; size differs")
    if int(row["revision"]) > 1 or recent_status == "UPDATED":
        status = "UPDATED"
    elif recent_status == "NEW":
        status = "NEW"
    else:
        status = "MISSING"
    return Comparison(code, name, status, target)
