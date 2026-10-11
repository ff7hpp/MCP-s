"""Track newly visible EWI academic items without writing to the portal."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error

from app.config import PROJECT_ROOT
from app.ewi import portal
from app.lms.browser import LoginError

STATE_PATH = PROJECT_ROOT / "data" / "ewi_updates.json"
TIMEZONE = timezone(timedelta(hours=3), name="Europe/Istanbul")


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _identity(section: str, item: dict[str, object]) -> object:
    if section in {"notifications", "news"}:
        return item.get("url") or item
    if section == "schedule":
        return [item.get("date"), item.get("course_code"), item.get("time")]
    if section in {"exam_results", "absences"}:
        values = item.get("values") or []
        return values[0] if values else item
    if section == "course_resources":
        values = item.get("values") or []
        return [
            item.get("semester"),
            values[0] if values else None,
            values[2] if len(values) > 2 else None,
        ]
    if section == "courses":
        return [item.get("semester"), item.get("course_code"), item.get("section")]
    if section == "transcript":
        return item.get("semester")
    return item


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "scanned_at": None, "sections": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("EWI_STATE_INVALID: existing update state cannot be read") from exc
    if state.get("version") != 1 or not isinstance(state.get("sections"), dict):
        raise RuntimeError("EWI_STATE_INVALID: unsupported update state version")
    return state


def _save(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="ewi_updates_",
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


def _read_transcript() -> list[dict[str, object]]:
    return portal.get_transcript()["semesters"]


def _news_detail(item: dict[str, object]) -> dict[str, object]:
    result = dict(item)
    url = str(item.get("url") or "")
    news_id = parse_qs(urlparse(url).query).get("NewsID", [""])[0]
    if news_id.isdigit():
        try:
            detail = portal.get_news_detail(int(news_id))
            result["title"] = detail["title"] or item.get("title")
            result["content"] = detail["content"]
        except (LoginError, RuntimeError, Error):
            result["detail_unavailable"] = True
    return result


def _recent(items: list[dict[str, object]], section: str) -> list[dict[str, object]]:
    date_format = "%d.%m.%Y %H:%M" if section == "notifications" else "%d.%m.%Y"

    def posted(item: dict[str, object]) -> datetime:
        try:
            return datetime.strptime(str(item.get("date") or ""), date_format).replace(
                tzinfo=TIMEZONE
            )
        except ValueError:
            return datetime.min.replace(tzinfo=TIMEZONE)

    return sorted(items, key=posted, reverse=True)[:5]


def scan_updates(state_path: Path = STATE_PATH) -> dict[str, object]:
    """Scan EWI and compare with last successful local snapshot; first scan sets baseline."""
    state = _load(state_path)
    previous_scan_at = state.get("scanned_at")
    previous_sections = state["sections"]
    readers = {
        "notifications": portal.get_notifications,
        "news": portal.get_news,
        "schedule": portal.get_schedule,
        "exam_results": portal.get_exam_results,
        "absences": portal.get_absences,
        "course_resources": portal.get_course_resources,
        "courses": portal.list_courses,
        "transcript": _read_transcript,
    }
    changes: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    baseline_sections: list[str] = []
    scanned_sections: list[str] = []
    latest: dict[str, object] = {}
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")

    for section, read in readers.items():
        try:
            items = read()
        except LoginError:
            raise
        except (RuntimeError, ValueError, OSError, Error) as exc:
            errors[section] = str(exc).splitlines()[0]
            continue
        scanned_sections.append(section)
        previous = previous_sections.get(section)
        old_items = previous.get("items", {}) if isinstance(previous, dict) else {}
        current: dict[str, str] = {}
        for item in items:
            key = _digest(_identity(section, item))
            fingerprint = _digest(item)
            current[key] = fingerprint
            if previous is None or old_items.get(key) == fingerprint:
                continue
            enriched = _news_detail(item) if section == "news" else item
            changes.append(
                {
                    "section": section,
                    "status": "UPDATED" if key in old_items else "NEW",
                    "item": enriched,
                }
            )
        if previous is None:
            baseline_sections.append(section)
        previous_sections[section] = {"scanned_at": now, "items": current}
        if section in {"notifications", "news"}:
            recent = _recent(items, section)
            latest[section] = (
                [
                    _news_detail(item) if item.get("title") in {None, "", "No Title"} else item
                    for item in recent
                ]
                if section == "news"
                else recent
            )

    if scanned_sections:
        state["scanned_at"] = now
        _save(state_path, state)
    return {
        "scanned_at": now,
        "previous_scan_at": previous_scan_at,
        "baseline_sections": baseline_sections,
        "scanned_sections": scanned_sections,
        "scan_errors": errors,
        "new_count": sum(item["status"] == "NEW" for item in changes),
        "updated_count": sum(item["status"] == "UPDATED" for item in changes),
        "changes": changes,
        "latest": latest,
        "state_saved": bool(scanned_sections),
    }
