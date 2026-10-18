"""Read-only course metadata scanner based on inspected LMS pages."""

import re
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import Locator, Page

from app.config import LMS_URL
from app.lms.browser import authenticated_context
from app.lms.courses import Course, discover_courses
from app.lms.models import Announcement, CalendarEvent, CourseSnapshot, RemoteFile, Resource

BASE = urlparse(LMS_URL)
RESOURCE_PATH = "/web/Uzem/Ogrenci/Dersler/DersKaynaklari"
NEWS_PATH = "/web/Uzem/News/ReadNews"
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


def _resources(page: Page, course: Course) -> list[Resource]:
    card = _card(page, "Course Resources")
    tables = card.locator("table").filter(
        has=page.get_by_role("columnheader", name="Resource Title")
    )
    if tables.count() == 0:
        if card.locator(".uzem-course-empty-row").count():
            return []
        raise RuntimeError("RESOURCE_TABLE_NOT_FOUND")
    resources: list[Resource] = []
    for row in tables.first.locator("tbody tr").all():
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
    return resources


def _announcements(page: Page, course: Course) -> list[Announcement]:
    card = _card(page, "Course News")
    announcements: list[Announcement] = []
    for row in card.locator(".uzem-detail-list-row").all():
        link = row.locator("a").first
        url, query = _verified_link(link.get_attribute("href"), NEWS_PATH, "NewsID", "SID")
        if query["SID"] != parse_qs(urlparse(course.url or "").query).get("SID"):
            raise RuntimeError("NEWS_LINK_INVALID: course identifier differs")
        announcements.append(
            Announcement(
                title=link.inner_text().strip(),
                posted_at=row.locator("time").first.inner_text().strip(),
                url=url,
            )
        )
    return announcements


def _exams(page: Page) -> list[dict[str, str]]:
    card = _card(page, "Exam Information")
    if card.locator(".uzem-course-exam-empty").count():
        return []
    raw_text = card.locator(".yoo-card-body").first.inner_text().strip()
    if not raw_text:
        return []
    return [{"title": "Exam information", "raw_text": raw_text}]


def _calendar(page: Page) -> tuple[str, list[CalendarEvent]]:
    card = _card(page, "Course Calendar")
    calendar = card.locator("#UzemCourseCalendar")
    if calendar.count() == 0:
        raise RuntimeError("CALENDAR_NOT_FOUND")
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
                    location=row.locator("p").first.inner_text().strip()
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
    description = meta.locator(".uzem-resource-description p").first.inner_text().strip()
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
    hours = _course_hours(page)
    resources = _resources(page, course)
    announcements = _announcements(page, course)
    exams = _exams(page)
    scope, events = _calendar(page)
    detailed_resources = [_resource_details(page, course, resource) for resource in resources]
    detailed_announcements = [_announcement_detail(page, item) for item in announcements]
    return CourseSnapshot(
        course, hours, detailed_resources, detailed_announcements, exams, events, scope
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
