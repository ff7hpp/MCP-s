"""Durable local JSON state, bounded backups, and process-wide operation locking."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock, local

from app.config import PROJECT_ROOT
from app.errors import ActionableError

_LOCK = RLock()
_LOCAL = local()
LOCK_PATH = PROJECT_ROOT / "data" / "operation.lock"


@contextmanager
def operation_lock(path: Path | None = None, *, wait_seconds: float = 0):
    """Bounded operation queue; OS releases locks even after a killed process."""
    path = path or LOCK_PATH
    deadline = time.monotonic() + wait_seconds
    if not _LOCK.acquire(timeout=max(0, wait_seconds)):
        raise ActionableError(
            "SCAN_BUSY: operation still running; retry_after_seconds=15; cached data retains its verification time"
        )
    handle = None
    acquired = False
    try:
        if not getattr(_LOCAL, "depth", 0):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a+b")
            handle.seek(0)
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ActionableError(
                            "SCAN_BUSY: operation still running; retry_after_seconds=15"
                        ) from exc
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        _LOCAL.depth = getattr(_LOCAL, "depth", 0) + 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
    finally:
        if handle:
            if acquired and os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()
        _LOCK.release()


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with operation_lock(wait_seconds=15):
            return function(*args, **kwargs)

    return wrapped


def digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".bak", dir=directory)
    os.close(handle)
    target = Path(name)
    shutil.copyfile(path, target)
    for old in sorted(directory.glob(f"{path.name}.*.bak"), key=lambda p: p.stat().st_mtime_ns)[
        :-5
    ]:
        old.unlink()
    return target


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "scanned_at": None, "sections": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(state, dict)
            or type(state.get("version")) is not int
            or state["version"] != 1
        ):
            raise ValueError("version")
        if not isinstance(state.get("sections"), dict):
            raise TypeError("sections")
        if path.name.startswith(("ewi_updates.json", "uzem_updates.json")):
            for section in state["sections"].values():
                _validate_section(section)
        if path.name.startswith("sync_records.json"):
            for record in state["sections"].values():
                validate_sync_record(record)
        if path.name.startswith("syllabus_state.json"):
            for record in state["sections"].values():
                if (
                    not isinstance(record, dict)
                    or not isinstance(record.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                    or not isinstance(record.get("scanned_at"), str)
                ):
                    raise ActionableError("SYLLABUS_STATE_INVALID: recover a checked backup")
        if path.name.startswith("university_alerts.json") and any(
            not isinstance(record, dict)
            or ("last_seen_at" in record and not isinstance(record["last_seen_at"], str))
            for record in state["sections"].values()
        ):
            raise ActionableError("ALERT_STATE_INVALID: recover a checked backup")
        return state
    except (OSError, ValueError, TypeError) as exc:
        raise ActionableError(
            "STATE_INVALID: preserve original; recover from data/backups"
        ) from exc


def validate_sync_record(record: object) -> None:
    if (
        not isinstance(record, dict)
        or not all(isinstance(record.get(key), str) for key in ("path", "revision", "sha256"))
        or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        # Legacy completed receipts predate the pending/install journal.
        or record.get("status", "installed") not in {"installed", "pending"}
        or type(record.get("size")) is not int
        or record["size"] <= 0
    ):
        raise ActionableError("SYNC_STATE_INVALID: preserve original and recover a checked backup")


@serialized
def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        backup_file(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@serialized
def recover_state(path: Path, backup: Path) -> None:
    """Explicit recovery validates a backup before replacing any original."""
    if backup.resolve().parent != (path.parent / "backups").resolve():
        raise ValueError("BACKUP_OUTSIDE_STATE_DIRECTORY")
    if not backup.is_file() or backup.is_symlink() or backup.is_junction():
        raise ActionableError("BACKUP_NOT_FOUND: choose an existing regular backup file")
    if not backup.name.startswith(path.name + "."):
        raise ActionableError("BACKUP_TYPE_MISMATCH: choose a backup for this state file")
    save_state(path, load_state(backup))


def _validate_section(section: object) -> None:
    if not isinstance(section, dict):
        raise TypeError("STATE_SECTION_INVALID: section must be an object")
    if not isinstance(section.get("items"), dict) or not isinstance(
        section.get("labels", {}), dict
    ):
        raise TypeError("STATE_SECTION_INVALID: items and labels must be objects")
    if not all(isinstance(value, str) for value in section["items"].values()):
        raise TypeError("STATE_SECTION_INVALID: fingerprints must be strings")
    if not all(isinstance(value, dict) for value in section.get("labels", {}).values()):
        raise TypeError("STATE_SECTION_INVALID: labels must be objects")


def compare_section(
    state: dict, section: str, items: list[dict], identity, now: str
) -> tuple[list[dict], bool]:
    """Hash private values; retain only a narrow label for disappeared items."""
    previous = state["sections"].get(section)
    if previous is not None:
        _validate_section(previous)
    old_items = previous.get("items", {}) if previous else {}
    labels = previous.get("labels", {}) if previous else {}
    current = {}
    current_labels = {}
    changes = []
    for item in items:
        key = digest(identity(section, item))
        fingerprint = digest(item)
        if key in current:
            raise ValueError("DUPLICATE_ITEM_IDENTITY: comparison is incomplete")
        current[key] = fingerprint
        current_labels[key] = {
            name: item[name]
            for name in ("title", "name", "course_code", "course_id", "url", "date")
            if name in item
        }
        if previous and old_items.get(key) != fingerprint:
            changes.append(
                {
                    "section": section,
                    "status": "UPDATED" if key in old_items else "NEW",
                    "item": item,
                }
            )
    for key in old_items.keys() - current.keys():
        changes.append(
            {
                "section": section,
                "status": "REMOVED",
                "item": labels.get(key, {"identity": key}),
                "meaning": "No longer visible in this successfully scanned scope; cancellation not inferred",
            }
        )
    state["sections"][section] = {"scanned_at": now, "items": current, "labels": current_labels}
    return changes, previous is None
