"""Local project paths and non-secret configuration."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

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
    term: str = "Fall 2026/2027"
    drive_root: Path | None = None


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as handle:
        values = tomllib.load(handle)
    raw_root = values.get("drive_root")
    root = Path(raw_root).expanduser() if raw_root else None
    return Config(term=values.get("term", Config.term), drive_root=root)


def save_drive_root(root: Path, path: Path = CONFIG_PATH) -> None:
    """Save only local path and term; never write credentials."""
    term = load_config(path).term
    escaped_root = str(root.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    escaped_term = term.replace('"', '\\"')
    path.write_text(f'term = "{escaped_term}"\ndrive_root = "{escaped_root}"\n', encoding="utf-8")
