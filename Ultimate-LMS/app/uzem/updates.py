"""Compare read-only UZEM scans with a local baseline."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import PROJECT_ROOT
from app.storage.state import compare_section, serialized
from app.storage.state import load_state as _load
from app.storage.state import save_state as _save
from app.uzem import portal

STATE_PATH = PROJECT_ROOT / "data" / "uzem_updates.json"
TIMEZONE = timezone(timedelta(hours=3), name="Europe/Istanbul")


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
        "files": snapshot.get("files", []),
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


@serialized
def scan_updates(
    state_path: Path = STATE_PATH, *, include_private: bool = False
) -> dict[str, object]:
    snapshot = portal.scan_all(include_grades=include_private)
    state = _load(state_path)
    previous_scan_at = state["scanned_at"]
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    items_by_section = _items(snapshot)
    errors = snapshot["scan_errors"]
    failed_courses = [key for key in errors if key.startswith("course:")]
    if failed_courses:
        for section in ("activities", "files", "announcements"):
            errors.setdefault(section, "UZEM_COURSE_SCAN_INCOMPLETE: " + ", ".join(failed_courses))
    changes = []
    baseline_sections = []
    scanned_sections = []
    for section, items in items_by_section.items():
        if section == "grades" and not include_private:
            continue
        if section in errors or (
            section in {"activities", "files", "announcements"}
            and any(key.startswith("course:") for key in errors)
        ):
            continue
        try:
            section_changes, baseline = compare_section(state, section, items, _identity, now)
        except (ValueError, TypeError) as exc:
            errors[section] = str(exc)
            continue
        changes.extend(section_changes)
        if baseline:
            baseline_sections.append(section)
        scanned_sections.append(section)
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
        "removed_count": sum(item["status"] == "REMOVED" for item in changes),
        "changes": changes,
        "current": {key: items_by_section[key] for key in scanned_sections},
        "section_status": {
            key: {
                "scanned_at": now if key in scanned_sections else None,
                "last_successful_at": state["sections"].get(key, {}).get("scanned_at"),
                "freshness": "FRESH"
                if key in scanned_sections
                else "STALE"
                if key in state["sections"]
                else "UNKNOWN",
                "completeness": "COMPLETE_IN_SCOPE" if key in scanned_sections else "INCOMPLETE",
            }
            for key in set(items_by_section) | set(errors)
            if key != "grades" or include_private
        },
        "change_meaning": "NEW means newly visible versus prior scan, not necessarily newly posted",
        "state_saved": bool(scanned_sections),
    }
