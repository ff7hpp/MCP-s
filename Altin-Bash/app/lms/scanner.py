"""Read-only course metadata scanner based on inspected LMS pages."""

import json
import re
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.config import LMS_URL
from app.errors import ActionableError
from app.lms.assignments import ISTANBUL, read_assignments
from app.lms.browser import authenticated_context
from app.lms.courses import Course, discover_courses
from app.lms.models import Announcement, CalendarEvent, CourseSnapshot, RemoteFile, Resource
from app.lms.readonly import require_single_page
from app.lms.sections import course_links

BASE = urlparse(LMS_URL)
RESOURCE_PATH = "/web/Uzem/Ogrenci/Dersler/DersKaynaklari"
RESOURCE_IDS = re.compile(
    r"DersKaynaklari\?Action=Details(?:&|&amp;)SID=(\d+)(?:&|&amp;)CRID=(\d+)"
)


def _card(page: Page, title: str) -> Locator:
    heading = page.locator("h2").filter(has_text=title).first
    if heading.count() != 1:
        raise RuntimeError(f"COURSE_LAYOUT_CHANGED: {title} section missing")
    return heading.locator(
        'xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," yoo-card ")][1]'
    )


def _lms_url(path: str, **query: str) -> str:
    return urlunparse((BASE.scheme, BASE.netloc, path, "", urlencode(query), ""))


def _verified_link(
    url: str | None, path: str, *numeric_keys: str
) -> tuple[str, dict[str, list[str]]]:
    if not url:
        raise RuntimeError("LMS_LINK_INVALID: empty URL")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.scheme != "https" or parsed.netloc != BASE.netloc or parsed.path != path:
        raise RuntimeError("LMS_LINK_INVALID: unexpected destination")
    if any(len(query.get(key, [])) != 1 or not query[key][0].isdigit() for key in numeric_keys):
        raise RuntimeError("LMS_LINK_INVALID: missing numeric identifier")
    return url, query


def _resource_url(onclick: str | None, course: Course) -> str:
    match = RESOURCE_IDS.search(onclick or "")
    course_query = parse_qs(urlparse(course.url or "").query)
    if not match or course_query.get("SID") != [match.group(1)]:
        raise RuntimeError("RESOURCE_LINK_INVALID: course/resource identifiers differ")
    return _lms_url(RESOURCE_PATH, Action="Details", SID=match.group(1), CRID=match.group(2))


def _course_hours(page: Page) -> dict[str, str]:
    info = _card(page, "Course Information")
    hours: dict[str, str] = {}
    for item in info.locator(".uzem-course-hours-row > div").all():
        label = item.locator("span").first.inner_text().strip().lower()
        value = item.locator("b").first.inner_text().strip()
        hours[label] = value
    return hours


def _resources(page: Page, course: Course, errors=None) -> list[Resource]:
    require_single_page(page)
    card = _card(page, "Course Resources")
    tables = card.locator("table").filter(
        has=page.get_by_role("columnheader", name="Resource Title")
    )
    if tables.count() == 0:
        if card.locator(".uzem-course-empty-row").count():
            return []
        raise RuntimeError("RESOURCE_TABLE_NOT_FOUND")
    resources: list[Resource] = []
    for index, row in enumerate(tables.first.locator("tbody tr").all()):
        try:
            cells = [value.strip() for value in row.locator("td").all_inner_texts()]
            if len(cells) < 4:
                raise RuntimeError("RESOURCE_TABLE_INVALID: expected four columns")
            resources.append(
                Resource(
                    title=cells[0],
                    uploader=cells[1],
                    file_count=int(cells[2]),
                    created_at=cells[3],
                    url=_resource_url(row.get_attribute("onclick"), course),
                )
            )
        except Exception as exc:
            if errors is None:
                raise
            errors[f"resources:row:{index}"] = f"RESOURCE_LIST_ITEM_FAILED: {type(exc).__name__}"
    return resources


def _exams(page: Page) -> list[dict[str, object]]:
    card = _card(page, "Exam Information")
    if card.locator(".uzem-course-exam-empty").count():
        return []
    tables = card.locator("table")
    if tables.count() == 1:
        headers = [value.strip() for value in tables.locator("thead th").all_inner_texts()]
        if not headers:
            raise RuntimeError("EXAM_LAYOUT_CHANGED: table headers missing")
        exams = []
        for row in tables.locator("tbody tr").all():
            cells = [value.strip() for value in row.locator("td").all_inner_texts()]
            if len(cells) != len(headers):
                raise RuntimeError("EXAM_LAYOUT_CHANGED: table columns changed")
            values = dict(zip(headers, cells, strict=True))
            title = next(
                (
                    values[key]
                    for key in ("Exam Name", "Assessment", "Exam", "Title")
                    if values.get(key)
                ),
                "Exam information",
            )
            raw_date = values.get("Exam Date") or values.get("Date")
            date = None
            for pattern in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    parsed = datetime.strptime(raw_date or "", pattern).replace(tzinfo=ISTANBUL)
                    date = parsed.isoformat() if "%H" in pattern else parsed.date().isoformat()
                    break
                except ValueError:
                    pass
            exams.append(
                {
                    "title": title,
                    "date": date,
                    "date_raw": raw_date,
                    "date_status": "Confirmed" if date else "Unknown",
                    "weight": values.get("Weight") or values.get("Percentage"),
                    "location": values.get("Location") or values.get("Room"),
                    "source_url": page.url,
                    "source_fields": values,
                }
            )
        return exams
    raw_text = card.locator(".yoo-card-body").first.inner_text().strip()
    if not raw_text:
        raise RuntimeError("EXAM_LAYOUT_CHANGED: no explicit empty state")
    return [
        {
            "title": "Exam information",
            "raw_text": raw_text,
            "date": None,
            "weight": None,
            "location": None,
            "date_status": "Unknown",
        }
    ]


def _embedded_calendar(page: Page) -> tuple[str, list[CalendarEvent]] | None:
    """Read the observed FullCalendar JSON array even when the portal script cannot run."""
    payloads = []
    for script in page.locator("script").all_text_contents():
        if "UzemCourseCalendar" not in script:
            continue
        if len(script) > 1_000_000:
            raise ActionableError("CALENDAR_PAYLOAD_TOO_LARGE")
        constructor = re.search(
            r"new\s+FullCalendar\.Calendar\(\s*CalendarElement\s*,\s*\{", script
        )
        if not constructor:
            continue
        match = re.search(r"\bevents\s*:\s*(\[)", script[constructor.end() :])
        if match:
            start = constructor.end() + match.start(1)
            try:
                payload, end = json.JSONDecoder().raw_decode(script[start:])
                if not script[start + end :].lstrip().startswith((",", "}")):
                    raise ValueError("calendar events must be a literal JSON array")
            except ValueError as exc:
                raise ActionableError("CALENDAR_PAYLOAD_INVALID: events must be JSON data") from exc
            payloads.append(payload)
    if not payloads:
        return None
    if len(payloads) != 1 or not isinstance(payloads[0], list) or len(payloads[0]) > 2000:
        raise ActionableError("CALENDAR_PAYLOAD_INVALID: ambiguous or oversized event list")
    events, seen = [], set()
    for item in payloads[0]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("title"), str)
            or not isinstance(item.get("start"), str)
        ):
            raise ActionableError("CALENDAR_PAYLOAD_INVALID: event fields changed")
        try:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"]) if item.get("end") else None
        except (ValueError, TypeError) as exc:
            raise ActionableError("CALENDAR_PAYLOAD_INVALID: explicit ISO dates required") from exc
        if start.tzinfo or (end and end.tzinfo):
            raise ActionableError(
                "CALENDAR_PAYLOAD_UNSUPPORTED: offset timestamps need explicit timezone handling"
            )
        remote_id = str(item.get("id") or "")
        identity = remote_id or (item["title"], item["start"], item.get("end"))
        if identity in seen:
            raise ActionableError("CALENDAR_PAYLOAD_INVALID: duplicate event identity")
        seen.add(identity)
        timing = ""
        if "T" in item["start"] and not item.get("allDay"):
            timing = start.strftime("%H:%M")
            if end and end.date() == start.date() and end > start:
                timing += "-" + end.strftime("%H:%M")
        properties = item.get("extendedProps", {})
        if not isinstance(properties, dict) or not isinstance(
            properties.get("description", ""), str
        ):
            raise ActionableError("CALENDAR_PAYLOAD_INVALID: event description changed")
        events.append(
            CalendarEvent(
                date=start.date().isoformat(),
                title=item["title"],
                time=timing,
                location=str(properties.get("location") or ""),
                remote_id=remote_id,
                description=properties.get("description", ""),
                source_url=page.url,
                event_type=str(properties.get("type") or ""),
                end_date=end.isoformat() if end else "",
            )
        )
    dates = sorted(event.date for event in events)
    scope = "Embedded LMS calendar JSON; " + (
        f"{dates[0]} through {dates[-1]}" if dates else "explicitly empty payload"
    )
    return scope, events


def _calendar(page: Page) -> tuple[str, list[CalendarEvent]]:
    card = _card(page, "Course Calendar")
    calendar = card.locator("#UzemCourseCalendar")
    if calendar.count() == 0:
        raise RuntimeError("CALENDAR_NOT_FOUND")
    embedded = _embedded_calendar(page)
    if embedded is not None:
        return embedded
    calendar.locator(".fc-toolbar-title").first.wait_for(timeout=5000)
    scope = calendar.locator(".fc-toolbar-title").first.inner_text().strip()
    dates: list[str] = []
    for marker in calendar.locator(".fc-event").all():
        date = marker.locator("xpath=ancestor::td[@data-date][1]").get_attribute("data-date")
        if date and date not in dates:
            dates.append(date)
    events: list[CalendarEvent] = []
    for date in dates:
        marker = calendar.locator(f'td[data-date="{date}"] .fc-event').first
        marker.click()
        for row in card.locator(".uzem-calendar-event-row").all():
            events.append(
                CalendarEvent(
                    date=date,
                    title=row.locator("strong").first.inner_text().strip(),
                    time=row.locator("time").first.inner_text().strip(),
                    description=row.locator("p").first.inner_text().strip()
                    if row.locator("p").count()
                    else "",
                )
            )
    return scope, events


def _resource_details(page: Page, course: Course, resource: Resource) -> Resource:
    page.goto(resource.url, wait_until="domcontentloaded", timeout=30000)
    meta = page.locator(".uzem-resource-meta")
    if meta.count() != 1:
        raise RuntimeError("RESOURCE_DETAILS_NOT_FOUND")
    paragraphs = meta.locator(".uzem-resource-description p")
    description = paragraphs.first.inner_text().strip() if paragraphs.count() else ""
    files: list[RemoteFile] = []
    table = page.locator("table").filter(has=page.get_by_role("columnheader", name="File Name"))
    if table.count() == 0 and resource.file_count == 0:
        return replace(resource, description=description, files=[])
    if table.count() != 1:
        raise RuntimeError("RESOURCE_TABLE_NOT_FOUND: files table missing")
    for row in table.first.locator("tbody tr").all():
        cells = [value.strip() for value in row.locator("td").all_inner_texts()]
        if len(cells) < 3:
            raise RuntimeError("RESOURCE_FILE_INVALID: expected name, size, and date")
        link = row.locator('a[title="Download File"]').first
        if not link.count():
            raise RuntimeError("RESOURCE_FILE_LINK_MISSING")
        url, query = _verified_link(
            link.get_attribute("href"), RESOURCE_PATH, "SID", "CRID", "DownloadFile"
        )
        expected_query = parse_qs(urlparse(resource.url).query)
        if query["SID"] != expected_query["SID"] or query["CRID"] != expected_query["CRID"]:
            raise RuntimeError("RESOURCE_FILE_INVALID: resource identifier differs")
        files.append(
            RemoteFile(
                name=cells[0],
                size=cells[1],
                created_at=cells[2],
                download_url=url,
                remote_id=query["DownloadFile"][0],
            )
        )
    if len(files) != resource.file_count:
        raise RuntimeError("RESOURCE_FILE_COUNT_MISMATCH")
    return replace(resource, description=description, files=files)


def _announcement_detail(page: Page, announcement: Announcement) -> Announcement:
    page.goto(announcement.url, wait_until="domcontentloaded", timeout=30000)
    card = page.locator(".yoo-card").filter(has=page.locator(".uzem-news-detail-heading"))
    if card.count() != 1:
        raise RuntimeError("NEWS_DETAILS_NOT_FOUND")
    content = card.locator(".yoo-card-body").first.inner_text().strip()
    return replace(announcement, content=content)


def scan_course_page(page: Page, course: Course) -> CourseSnapshot:
    if not course.url:
        raise RuntimeError("COURSE_URL_MISSING")
    _verified_link(course.url, "/web/Uzem/Ogrenci/Dersler/DersDetay", "SID")
    page.goto(course.url, wait_until="domcontentloaded", timeout=30000)
    info = _card(page, "Course Information")
    code = (
        info.locator(".uzem-course-info-row")
        .filter(has=page.locator("strong", has_text="Course Code"))
        .locator("span")
        .first.inner_text()
        .strip()
    )
    if code != course.course_code:
        raise RuntimeError("COURSE_ID_MISMATCH")
    errors = {}

    def read(name, reader, default):
        try:
            return reader()
        except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
            message = str(exc).splitlines()[0] if str(exc) else ""
            errors[name] = (
                message[:200]
                if re.match(r"^[A-Z][A-Z_]+", message)
                else f"SECTION_SCAN_FAILED: {type(exc).__name__}"
            )
            return default

    hours = read("weekly_hours", lambda: _course_hours(page), {})
    resources = read("resources", lambda: _resources(page, course, errors), [])
    exams = read("exams", lambda: _exams(page), [])
    live, links = read("live_lessons", lambda: course_links(page), ([], []))
    if "live_lessons" in errors:
        errors["study_links"] = errors["live_lessons"]
    warnings: list[str] = []
    try:
        scope, events = _calendar(page)
    except PlaywrightTimeoutError:
        scope, events = "Unavailable", []
        warnings.append("CALENDAR_UNAVAILABLE: LMS calendar did not load")
    except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
        scope, events = "Unavailable", []
        warnings.append(f"CALENDAR_UNAVAILABLE: {type(exc).__name__}")
    if warnings:
        errors["calendar_events"] = "; ".join(warnings)
    detailed_resources = []
    for resource in resources:
        try:
            detailed_resources.append(_resource_details(page, course, resource))
        except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
            error = f"RESOURCE_DETAIL_FAILED: {type(exc).__name__}"
            errors[f"resources:{resource.url}"] = error
            detailed_resources.append(replace(resource, detail_error=error))
    if any(key.startswith("resources") for key in errors):
        errors["files"] = "RESOURCE_FILES_PARTIAL: one or more resources could not be read"
    from app.lms.announcements import news_list

    announcements = read("announcements", lambda: news_list(page, course, errors), [])
    detailed_announcements = []
    for item in announcements:
        try:
            detailed_announcements.append(_announcement_detail(page, item))
        except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
            error = f"NEWS_DETAIL_FAILED: {type(exc).__name__}"
            errors[f"announcements:{item.url}"] = error
            detailed_announcements.append(replace(item, detail_error=error))
    assignments = read("assignments", lambda: read_assignments(page, course, errors), [])
    return CourseSnapshot(
        course,
        hours,
        detailed_resources,
        detailed_announcements,
        exams,
        events,
        scope,
        warnings,
        assignments,
        live,
        links,
        errors,
    )


def scan_course(course_code: str) -> CourseSnapshot:
    with authenticated_context() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
        courses = discover_courses(page)
        course = next(
            (
                course
                for course in courses
                if course.course_code.casefold() == course_code.casefold()
            ),
            None,
        )
        if course is None:
            raise RuntimeError(f"COURSE_NOT_FOUND: {course_code}")
        return scan_course_page(page, course)
