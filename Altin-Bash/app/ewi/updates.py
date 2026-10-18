"""Track newly visible EWI academic items without writing to the portal."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error

from app.config import PROJECT_ROOT
from app.ewi import portal
from app.lms.browser import LoginError
from app.storage.state import compare_section, serialized
from app.storage.state import load_state as _load
from app.storage.state import save_state as _save

STATE_PATH = PROJECT_ROOT / "data" / "ewi_updates.json"
TIMEZONE = timezone(timedelta(hours=3), name="Europe/Istanbul")


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
        except (LoginError, RuntimeError, Error) as exc:
            raise RuntimeError(
                "EWI_NEWS_DETAIL_UNAVAILABLE: preserve prior news fingerprint"
            ) from exc
    else:
        raise RuntimeError("EWI_NEWS_ID_INVALID: cannot verify article detail")
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


@serialized
def scan_updates(
    state_path: Path = STATE_PATH, *, include_private: bool = False
) -> dict[str, object]:
    """Scan EWI and compare with last successful local snapshot; first scan sets baseline."""
    state = _load(state_path)
    previous_scan_at = state.get("scanned_at")
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
    if not include_private:
        for section in ("exam_results", "absences", "transcript"):
            readers.pop(section)
    changes: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    baseline_sections: list[str] = []
    scanned_sections: list[str] = []
    latest: dict[str, object] = {}
    current_items = {}
    section_status = {}
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")

    with portal.read_batch():
        for section, read in readers.items():
            previous_time = state["sections"].get(section, {}).get("scanned_at")
            try:
                items = read()
                if section == "news":
                    items = [_news_detail(item) for item in items]
            except LoginError:
                raise
            except (RuntimeError, ValueError, OSError, Error) as exc:
                errors[section] = str(exc).splitlines()[0]
                section_status[section] = {
                    "scanned_at": None,
                    "last_successful_at": previous_time,
                    "freshness": "STALE" if previous_time else "UNKNOWN",
                    "completeness": "INCOMPLETE",
                }
                continue
            now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
            try:
                section_changes, baseline = compare_section(state, section, items, _identity, now)
            except (ValueError, TypeError) as exc:
                errors[section] = str(exc)
                continue
            changes.extend(section_changes)
            scanned_sections.append(section)
            section_status[section] = {
                "scanned_at": now,
                "last_successful_at": now,
                "freshness": "FRESH",
                "completeness": "COMPLETE_IN_SCOPE",
            }
            if baseline:
                baseline_sections.append(section)
            current_items[section] = items
            if section in {"notifications", "news"}:
                recent = _recent(items, section)
                latest[section] = recent

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
        "removed_count": sum(item["status"] == "REMOVED" for item in changes),
        "changes": changes,
        "latest": latest,
        "current": current_items,
        "section_status": section_status,
        "change_meaning": "NEW means newly visible versus prior scan, not necessarily newly posted",
        "state_saved": bool(scanned_sections),
    }
