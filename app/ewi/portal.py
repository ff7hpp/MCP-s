"""Read-only access to observed student-facing EWI portal pages."""

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Error, Page

from app.config import EWI_PROFILE_PATH
from app.lms.browser import LoginError, authenticated_context, is_ewi_authenticated
from app.lms.readonly import EWI_SECTION_PATHS, iter_pages, require_single_page

BASE = "https://ewi.altinbas.edu.tr"
SECTION_PATHS = EWI_SECTION_PATHS
COURSES_PATH = SECTION_PATHS["my_courses"]
SCHEDULE_PATH = SECTION_PATHS["schedules"]
RESULTS_PATH = SECTION_PATHS["exam_results"]
ABSENCE_PATH = SECTION_PATHS["absences"]
RESOURCES_PATH = SECTION_PATHS["course_resources"]
NOTIFICATIONS_PATH = SECTION_PATHS["notifications"]
NEWS_PATH = SECTION_PATHS["news"]
TRANSCRIPT_PATH = SECTION_PATHS["transcript"]

_ACTIVE_CONTEXT = ContextVar("ewi_read_context", default=None)


@contextmanager
def read_batch():
    existing = _ACTIVE_CONTEXT.get()
    if existing is not None:
        yield existing
        return
    with authenticated_context(EWI_PROFILE_PATH) as context:
        token = _ACTIVE_CONTEXT.set(context)
        try:
            yield context
        finally:
            _ACTIVE_CONTEXT.reset(token)


@dataclass(frozen=True)
class Course:
    course_code: str
    course_name: str
    section: str | None = None
    credit: str | None = None
    ects: str | None = None
    instructor: str | None = None
    semester: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class ScheduleItem:
    date: str
    weekday: str
    course_code: str
    course_name: str
    time: str | None = None
    location: str | None = None


def _page(page: Page, path: str) -> None:
    page.goto(urljoin(BASE, path), wait_until="domcontentloaded", timeout=30000)
    if not is_ewi_authenticated(page):
        raise LoginError(
            "EWI_SESSION_EXPIRED: run `python -m app.cli ewi-login` and sign in manually"
        )


def _tables(page: Page, required: tuple[str, ...] = ()) -> list[dict[str, object]]:
    tables = []
    for _ in iter_pages(page):
        page_tables = page.locator("table").evaluate_all(
            """tables => tables.map(table => ({
              semester: table.closest('.yoo-card')?.querySelector('.yoo-card-title')?.innerText.trim() || null,
              headers: [...table.querySelectorAll('thead th')].map(cell => cell.innerText.trim()),
              rows: [...table.querySelectorAll('tbody tr')].map(row => [...row.querySelectorAll('td')]
                .map(cell => cell.innerText.trim()))
            }))"""
        )
        matched = [table for table in page_tables if set(required) <= set(table["headers"])]
        if required and not matched:
            raise RuntimeError("EWI_TABLE_LAYOUT_CHANGED: required academic columns missing")
        tables.extend(matched)
    return tables


def read_section(section: str, max_chars: int = 20_000) -> dict[str, object]:
    """Read visible text from one fixed EWI menu page without activating page controls."""
    if section not in SECTION_PATHS:
        raise ValueError(f"EWI_SECTION_UNKNOWN: choose one of {', '.join(SECTION_PATHS)}")
    if not 1_000 <= max_chars <= 100_000:
        raise ValueError("EWI_MAX_CHARS_INVALID: use 1000 through 100000")
    path = SECTION_PATHS[section]
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, path)
        content = page.locator(".yoo-content")
        if content.count() != 1:
            raise RuntimeError("EWI_SECTION_LAYOUT_CHANGED: content area missing or ambiguous")
        full_text = content.inner_text().strip()
        title = content.locator(".yoo-card-title").first
        final_path = urlparse(page.url).path
        return {
            "section": section,
            "url": page.url,
            "redirected": final_path != path,
            "title": title.inner_text().strip() if title.count() else None,
            "text": full_text[:max_chars],
            "truncated": len(full_text) > max_chars,
        }


def get_transcript() -> dict[str, object]:
    """Read the displayed EWI transcript, including grades and portal GPA totals."""
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, TRANSCRIPT_PATH)
        require_single_page(page)
        tables = page.locator(".tra-donem-table")
        if not tables.count():
            raise RuntimeError("EWI_TRANSCRIPT_LAYOUT_CHANGED: semester tables missing")
        semesters: list[dict[str, object]] = []
        for table in tables.all():
            term = table.locator(".tra-donem-row-title th").first.inner_text().strip()
            courses = []
            for row in table.locator(".tra-donem-row-ders").all():
                cells = [value.strip() for value in row.locator(":scope > td").all_inner_texts()]
                if len(cells) != 4:
                    raise RuntimeError("EWI_TRANSCRIPT_LAYOUT_CHANGED: course row changed")
                courses.append(
                    {"category": cells[0], "course": cells[1], "ects": cells[2], "grade": cells[3]}
                )
            summary: dict[str, dict[str, str]] = {}
            for row in table.locator(".tra-donem-row-footer-table tbody tr").all():
                cells = [
                    value.strip()
                    for value in row.locator(":scope > th, :scope > td").all_inner_texts()
                ]
                if len(cells) == 4 and cells[0] in {"Semester", "Total"}:
                    summary[cells[0].lower()] = {
                        "ects_received": cells[1],
                        "ects_completed": cells[2],
                        "gpa": cells[3],
                    }
            if not summary.get("semester") or not summary.get("total"):
                raise RuntimeError("EWI_TRANSCRIPT_LAYOUT_CHANGED: GPA totals missing")
            semesters.append({"semester": term, "courses": courses, "summary": summary})
        return {
            "url": page.url,
            "semesters": semesters,
            "latest_total": semesters[-1]["summary"]["total"],
        }


def list_courses() -> list[dict[str, str | None]]:
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, COURSES_PATH)
        courses: list[dict[str, str | None]] = []
        tables = _tables(page)
        for table in tables:
            headers = table["headers"]
            if "Course Code" not in headers or "Course Name" not in headers:
                continue
            indexes = {name: headers.index(name) for name in headers}
            semester = table["semester"]
            for cells in table["rows"]:
                if len(cells) <= indexes["Course Name"]:
                    continue

                def get(name: str, row: list[str], columns: dict[str, int]) -> str | None:
                    return (
                        row[columns[name]] or None
                        if name in columns and len(row) > columns[name]
                        else None
                    )

                courses.append(
                    asdict(
                        Course(
                            course_code=cells[indexes["Course Code"]],
                            course_name=cells[indexes["Course Name"]],
                            section=get("Section", cells, indexes),
                            credit=get("Credit", cells, indexes),
                            ects=get("Ects", cells, indexes),
                            instructor=get("Instructor", cells, indexes),
                            semester=semester,
                            status=get("Status", cells, indexes),
                        )
                    )
                )
        if not courses:
            raise RuntimeError("EWI_COURSE_LAYOUT_CHANGED: course tables not found")
        return courses


def get_schedule() -> list[dict[str, str | None]]:
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, SCHEDULE_PATH)
        items = []
        for _ in iter_pages(page):
            posts = page.locator(".yoo-post.yoo-style3")
            if not posts.count():
                raise RuntimeError("EWI_SCHEDULE_LAYOUT_CHANGED: dated schedule cards missing")
            for post in posts.all():
                date = post.locator(".yoo-post-user-name").first.inner_text().strip()
                weekday = post.locator(".yoo-post-user-email").first.inner_text().strip()
                for row in post.locator(".dp-row").all():
                    columns = row.locator(":scope > div")
                    if columns.count() < 2:
                        continue
                    course = " ".join(columns.nth(0).inner_text().split())
                    timing = " ".join(columns.nth(1).inner_text().split())
                    match = re.match(r"^(\S+)\s+(.+)$", course)
                    time_match = re.search(r"\b\d{1,2}:\d{2}-\d{1,2}:\d{2}\b", timing)
                    if not match:
                        continue
                    items.append(
                        asdict(
                            ScheduleItem(
                                date=date,
                                weekday=weekday,
                                course_code=match.group(1),
                                course_name=match.group(2),
                                time=time_match.group(0) if time_match else None,
                                location=timing.partition("(")[2].rstrip(") ")
                                if "(" in timing
                                else None,
                            )
                        )
                    )
        return items


def _academic_rows(
    path: str, required: tuple[str, ...], *, include_semester: bool = False
) -> list[dict[str, object]]:
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, path)
        return [
            {
                "headers": table["headers"],
                "values": row,
                **({"semester": table["semester"]} if include_semester else {}),
            }
            for table in _tables(page, required)
            for row in table["rows"]
        ]


def get_exam_results() -> list[dict[str, object]]:
    return _academic_rows(RESULTS_PATH, ("Course Code", "Letter grade"))


def get_absences() -> list[dict[str, object]]:
    return _academic_rows(ABSENCE_PATH, ("Course Code", "Total"))


def get_course_resources() -> list[dict[str, object]]:
    return _academic_rows(RESOURCES_PATH, ("Course Code", "Resource"), include_semester=True)


def get_notifications() -> list[dict[str, str | None]]:
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, NOTIFICATIONS_PATH)
        rows = []
        for _ in iter_pages(page):
            if (
                not page.get_by_role("columnheader", name="Notification", exact=True).count()
                or not page.get_by_role("columnheader", name="Date", exact=True).count()
            ):
                raise RuntimeError("EWI_NOTIFICATION_LAYOUT_CHANGED")
            for row in (
                page.locator("table")
                .filter(has=page.get_by_role("columnheader", name="Notification"))
                .locator("tbody tr")
                .all()
            ):
                cells = row.locator("td").all()
                link = cells[0].locator("a").first if cells else None
                href = link.get_attribute("href") if link and link.count() else None
                url = urljoin(BASE, href) if href else None
                if url and (
                    urlparse(url).scheme != "https" or urlparse(url).netloc != urlparse(BASE).netloc
                ):
                    url = None
                rows.append(
                    {
                        "notification": cells[0].inner_text().strip() if cells else None,
                        "date": cells[1].inner_text().strip() if len(cells) > 1 else None,
                        "url": url,
                    }
                )
        return rows


def get_news() -> list[dict[str, str | None]]:
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, NEWS_PATH)
        result = []
        for _ in iter_pages(page):
            for link in page.locator('a[href*="/web/News/ReadNews"]').all():
                href = link.get_attribute("href")
                url = urljoin(BASE, href or "")
                if urlparse(url).netloc != urlparse(BASE).netloc:
                    continue
                row = link.locator("xpath=ancestor::tr[1]")
                result.append(
                    {
                        "title": link.inner_text().strip() or None,
                        "date": row.inner_text()
                        .strip()
                        .replace(link.inner_text().strip(), "")
                        .strip()
                        if row.count()
                        else None,
                        "url": url,
                    }
                )
        return result


def get_news_detail(news_id: int) -> dict[str, str | int]:
    """Read one EWI news article from its numeric portal identifier."""
    if news_id <= 0:
        raise ValueError("EWI_NEWS_ID_INVALID: positive numeric NewsID required")
    with read_batch() as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, f"/web/News/ReadNews?NewsID={news_id}")
        if urlparse(page.url).path != "/web/News/ReadNews":
            raise RuntimeError("EWI_NEWS_NOT_FOUND: portal redirected")
        card = page.locator(".yoo-content .yoo-card").first
        if not card.count() or not card.locator(".yoo-card-body").count():
            raise RuntimeError("EWI_NEWS_LAYOUT_CHANGED: article card missing")
        return {
            "news_id": news_id,
            "url": page.url,
            "title": card.locator(".yoo-card-title").first.inner_text().strip(),
            "date": card.locator(".yoo-card-heading-right").first.inner_text().strip(),
            "content": card.locator(".yoo-card-body").first.inner_text().strip(),
        }


def scan_all(*, include_private: bool = False) -> dict[str, object]:
    readers = {
        "courses": list_courses,
        "schedule": get_schedule,
        "course_resources": get_course_resources,
        "notifications": get_notifications,
        "news": get_news,
    }
    if include_private:
        readers.update(exam_results=get_exam_results, absences=get_absences)
    result = {"scan_errors": {}}
    with read_batch():
        for name, read in readers.items():
            try:
                result[name] = read()
            except (RuntimeError, ValueError, Error) as exc:
                result["scan_errors"][name] = str(exc).splitlines()[0][:200]
    return result
