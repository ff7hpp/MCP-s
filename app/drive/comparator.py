"""Conservative comparison of LMS metadata with local Drive files."""

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
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
    config: Config, course_code: str, resource_title: str, resource_url: str, filename: str
) -> Path:
    if config.drive_root is None:
        raise ValueError("DRIVE_NOT_CONFIGURED")
    term = safe_component(config.term.replace("/", "-"))
    resource_id = parse_qs(urlparse(resource_url).query).get("CRID", ["unknown"])[0]
    if not resource_id.isdigit():
        resource_id = "unknown"
    folder = f"{safe_component(resource_title)}__{resource_id}"
    return (
        config.drive_root
        / "University"
        / term
        / safe_component(course_code)
        / "LMS"
        / "Resources"
        / folder
        / safe_component(filename)
    )


def _course_dirs(root: Path, course_code: str) -> list[Path]:
    university = root / "University"
    if not university.is_dir():
        return []
    wanted = re.compile(rf"^{re.escape(course_code.casefold())}(?:$|[\s_-])")
    matches: list[Path] = []
    for parent, dirs, _ in os.walk(university, followlinks=False):
        for directory in list(dirs):
            candidate = Path(parent) / directory
            if candidate.is_symlink():
                dirs.remove(directory)
            elif wanted.match(directory.casefold()):
                matches.append(candidate)
                dirs.remove(directory)
    return matches


def compare_file(
    row: dict[str, object], config: Config, recent_status: str | None = None
) -> Comparison:
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    code = str(row["course_code"])
    name = str(row["name"])
    target = course_target(config, code, str(row["resource_title"]), str(row["resource_url"]), name)
    candidates: list[Path] = []
    wanted = normalized_name(name)
    for directory in _course_dirs(config.drive_root, code):
        for parent, _, files in os.walk(directory, followlinks=False):
            for filename in files:
                if normalized_name(filename) == wanted:
                    candidates.append(Path(parent) / filename)
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
