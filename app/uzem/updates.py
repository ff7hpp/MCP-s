"""Compare read-only UZEM scans with a local baseline."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import PROJECT_ROOT
from app.uzem import portal

STATE_PATH = PROJECT_ROOT / "data" / "uzem_updates.json"
TIMEZONE = timezone(timedelta(hours=3), name="Europe/Istanbul")


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _items(snapshot: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    activities = []
    for detail in snapshot["course_details"]:
        for section in detail["sections"]:
            for activity in section["activities"]:
                activities.append(
                    {"course_id": detail["course"]["id"], "section": section["title"], **activity}
                )
    grades = [
        {"course_id": course["course_id"], **row}
        for course in snapshot["grades"]
        for row in course["rows"]
    ]
    return {
        "courses": snapshot["courses"],
        "activities": activities,
        "files": snapshot["files"],
        "announcements": snapshot["announcements"],
        "notifications": snapshot["notifications"],
        "calendar": snapshot["calendar"],
        "grades": grades,
    }


def _identity(section: str, item: dict[str, object]) -> object:
    if section == "courses":
        return item.get("id")
    if section == "activities":
        return [item.get("course_id"), item.get("id")]
    if section == "grades":
        return [item.get("course_id"), item.get("item")]
    if section == "files":
        return [item.get("course_code"), item.get("remote_id")]
    return item.get("url") or [item.get("course_id"), item.get("title"), item.get("date")]


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "scanned_at": None, "sections": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("UZEM_STATE_INVALID: saved comparison state cannot be read") from exc
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("sections"), dict)
    ):
        raise RuntimeError("UZEM_STATE_INVALID: unsupported comparison state")
    return state


def _save(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="uzem_updates_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def scan_updates(state_path: Path = STATE_PATH) -> dict[str, object]:
    snapshot = portal.scan_all()
    state = _load(state_path)
    previous_scan_at = state["scanned_at"]
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    items_by_section = _items(snapshot)
    errors = snapshot["scan_errors"]
    changes = []
    baseline_sections = []
    scanned_sections = []
    for section, items in items_by_section.items():
        if section in errors or (
            section in {"activities", "files", "announcements"}
            and any(key.startswith("course:") for key in errors)
        ):
            continue
        old_section = state["sections"].get(section)
        old_items = old_section["items"] if old_section else {}
        current = {}
        for item in items:
            identity = _digest(_identity(section, item))
            fingerprint = _digest(item)
            current[identity] = fingerprint
            if old_section and old_items.get(identity) != fingerprint:
                changes.append(
                    {
                        "section": section,
                        "status": "UPDATED" if identity in old_items else "NEW",
                        "item": item,
                    }
                )
        if old_section is None:
            baseline_sections.append(section)
        scanned_sections.append(section)
        state["sections"][section] = {"scanned_at": now, "items": current}
    if scanned_sections:
        state["scanned_at"] = now
        _save(state_path, state)
    return {
        "scanned_at": now,
        "previous_scan_at": previous_scan_at,
        "baseline_sections": baseline_sections,
        "scanned_sections": scanned_sections,
        "scan_errors": errors,
        "new_count": sum(c["status"] == "NEW" for c in changes),
        "updated_count": sum(c["status"] == "UPDATED" for c in changes),
        "changes": changes,
        "current": {
            key: items_by_section[key]
            for key in ("courses", "announcements", "notifications", "calendar")
        },
        "state_saved": bool(scanned_sections),
    }
