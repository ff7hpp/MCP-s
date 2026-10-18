"""Local project paths and non-secret configuration."""

import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.errors import ActionableError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
PROFILE_PATH = PROJECT_ROOT / "browser-profile"
EWI_PROFILE_PATH = PROJECT_ROOT / "ewi-browser-profile"
UZEM_PROFILE_PATH = PROJECT_ROOT / "uzem-browser-profile"
LMS_URL = "https://lms.altinbas.edu.tr/web/Uzem"
EWI_URL = "https://ewi.altinbas.edu.tr/web/Main"
UZEM_URL = "https://uzem.altinbas.edu.tr/my/courses.php"


@dataclass(frozen=True)
class Config:
    term: str = "Unknown"
    drive_root: Path | None = None
    uzem_course_terms: dict[str, str] = field(default_factory=dict)
    cloud_account: str | None = None
    cloud_university_id: str | None = None
    cloud_course_folders: dict[str, str] = field(default_factory=dict)


def normalized_term(value: object) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(value, str):
        return None
    years = tuple(re.findall(r"20\d{2}", value))
    season = re.search(r"\b(fall|autumn|güz|spring|bahar|summer|yaz)\b", value, re.IGNORECASE)
    if len(years) != 2 or not season:
        return None
    name = season[1].casefold()
    return (
        "fall"
        if name in {"fall", "autumn", "güz"}
        else "spring"
        if name in {"spring", "bahar"}
        else "summer",
        years,
    )


def require_current_term(semester: object, configured: str) -> None:
    expected, observed = normalized_term(configured), normalized_term(semester)
    if expected is None or observed is None:
        raise ActionableError(
            "SOURCE_TERM_UNKNOWN: sync needs an explicit academic season and year range"
        )
    if expected != observed:
        raise ActionableError(
            "SOURCE_TERM_MISMATCH: portal semester differs from configured sync term"
        )


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as handle:
        values = tomllib.load(handle)
    raw_root = values.get("drive_root")
    term = values.get("term", Config.term)
    mapping = values.get("uzem_course_terms", {})
    if (term != "Unknown" and normalized_term(term) is None) or (
        raw_root is not None and not isinstance(raw_root, str)
    ):
        raise ActionableError("CONFIG_INVALID: expected academic term and local Drive path")
    if not isinstance(mapping, dict) or any(
        not key.isdecimal() or normalized_term(value) is None for key, value in mapping.items()
    ):
        raise ActionableError(
            "CONFIG_INVALID: UZEM term mappings require numeric course IDs and explicit terms"
        )
    root = Path(raw_root).expanduser() if raw_root else None
    cloud = values.get("cloud_course_folders", {})
    account, folder = values.get("cloud_account"), values.get("cloud_university_id")
    if (
        not isinstance(cloud, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", value)
            for key, value in cloud.items()
        )
        or (account is not None and (not isinstance(account, str) or len(account) > 254))
        or (
            folder is not None
            and (not isinstance(folder, str) or not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", folder))
        )
    ):
        raise ActionableError("CONFIG_INVALID: invalid connected Drive destination")
    return Config(
        term=term,
        drive_root=root,
        uzem_course_terms=mapping,
        cloud_account=account,
        cloud_university_id=folder,
        cloud_course_folders=cloud,
    )


def save_drive_root(root: Path, path: Path = CONFIG_PATH) -> None:
    """Save only local path and term; never write credentials."""
    save_config(replace(load_config(path), drive_root=root.resolve()), path)


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    from app.storage.state import backup_file, serialized

    @serialized
    def write():
        content = f"term = {json.dumps(config.term)}\n"
        for key in ("drive_root", "cloud_account", "cloud_university_id"):
            value = getattr(config, key)
            if value is not None:
                content += f"{key} = {json.dumps(str(value))}\n"
        for section in ("uzem_course_terms", "cloud_course_folders"):
            values = getattr(config, section)
            if values:
                content += f"\n[{section}]\n" + "".join(
                    f"{json.dumps(key)} = {json.dumps(value)}\n" for key, value in values.items()
                )
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            load_config(temporary)
            backup_file(path)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    write()
