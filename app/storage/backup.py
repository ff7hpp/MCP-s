"""Private, bounded recovery archives; restore only into a new staging directory."""

import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.config import PROJECT_ROOT
from app.storage.state import file_hash, serialized

STATE_FILES = (
    "state.sqlite",
    "ewi_updates.json",
    "uzem_updates.json",
    "sync_records.json",
    "syllabus_state.json",
    "university_alerts.json",
    "cloud_verifications.json",
    "operational_health.json",
)
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


@serialized
def create_backup(root: Path = PROJECT_ROOT, *, include_profiles=False) -> Path:
    directory = root / "data" / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("BACKUP_PATH_INVALID")
    target = directory / (
        "state-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".zip"
    )
    files = [(root / "config.toml", "config.toml")]
    files.extend((root / "data" / name, "data/" + name) for name in STATE_FILES)
    if include_profiles:
        for name in ("browser-profile", "ewi-browser-profile", "uzem-browser-profile"):
            profile = root / name
            if profile.is_symlink() or profile.is_junction():
                raise ValueError("BACKUP_PROFILE_LINK_REJECTED")
            for parent, dirs, names in os.walk(profile, followlinks=False):
                dirs[:] = [
                    value
                    for value in dirs
                    if value not in {"Cache", "Code Cache", "GPUCache", "ShaderCache", "DawnCache"}
                ]
                if any(
                    (Path(parent) / value).is_symlink() or (Path(parent) / value).is_junction()
                    for value in dirs
                ):
                    raise ValueError("BACKUP_PROFILE_LINK_REJECTED")
                files.extend(
                    (Path(parent) / value, (Path(parent) / value).relative_to(root).as_posix())
                    for value in names
                    if not value.startswith("Singleton")
                )
    manifest, total = {}, 0
    try:
        with (
            tempfile.TemporaryDirectory(dir=directory) as temporary,
            zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive,
        ):
            for path, name in files:
                if not path.exists():
                    continue
                if (
                    path.is_symlink()
                    or path.is_junction()
                    or not path.resolve().is_relative_to(root.resolve())
                ):
                    raise ValueError("BACKUP_SOURCE_PATH_INVALID")
                source = path
                if name == "data/state.sqlite":
                    source = Path(temporary) / "state.sqlite"
                    with (
                        closing(
                            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
                        ) as original,
                        closing(sqlite3.connect(source)) as copy,
                    ):
                        original.backup(copy)
                        if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("BACKUP_INTEGRITY_FAILED")
                total += source.stat().st_size
                if total > MAX_ARCHIVE_BYTES or len(manifest) >= 10000:
                    raise ValueError("BACKUP_RESOURCE_LIMIT")
                manifest[name] = {"sha256": file_hash(source), "size": source.stat().st_size}
                archive.write(source, name)
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        for old in sorted(directory.glob("state-*.zip"), key=lambda path: path.stat().st_mtime_ns)[
            :-5
        ]:
            old.unlink()
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


@serialized
def restore_to_new_directory(archive_path: Path, destination: Path) -> Path:
    if destination.exists():
        raise ValueError(
            "RESTORE_DESTINATION_EXISTS: choose a new directory; active state is never overwritten"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="restore-check-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 10001
                or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES
                or len({entry.filename for entry in entries}) != len(entries)
            ):
                raise ValueError("BACKUP_RESOURCE_LIMIT")
            if archive.getinfo("manifest.json").file_size > 3_000_000:
                raise ValueError("BACKUP_MANIFEST_INVALID")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or set(manifest) != {
                entry.filename for entry in entries
            } - {"manifest.json"}:
                raise ValueError("BACKUP_MANIFEST_INVALID")
            for entry in entries:
                if entry.filename == "manifest.json":
                    continue
                name = PurePosixPath(entry.filename)
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or "\\" in entry.filename
                    or ":" in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)
                ):
                    raise ValueError("BACKUP_MEMBER_PATH_INVALID")
                path = staging.joinpath(*name.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)
                if manifest[entry.filename] != {
                    "sha256": file_hash(path),
                    "size": path.stat().st_size,
                }:
                    raise ValueError("BACKUP_CONTENT_MISMATCH")
        database = staging / "data" / "state.sqlite"
        if database.is_file():
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("BACKUP_INTEGRITY_FAILED")
        staging.rename(destination)
        return destination
    finally:
        if (
            staging.exists()
            and staging.resolve().is_relative_to(destination.parent.resolve())
            and staging.name.startswith("restore-check-")
        ):
            shutil.rmtree(staging)
