"""Read-only access to observed student-facing EWI portal pages."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from app.config import EWI_PROFILE_PATH
from app.lms.browser import LoginError, authenticated_context, is_ewi_authenticated

BASE = "https://ewi.altinbas.edu.tr"
COURSES_PATH = "/web/Ogrenci/Dersler/Derslerim"
SCHEDULE_PATH = "/web/Ogrenci/Program/DersProgrami"
RESULTS_PATH = "/web/Ogrenci/Sonuclar/SinavSonuclari"
ABSENCE_PATH = "/web/Ogrenci/Dersler/Devamsizlik"
RESOURCES_PATH = "/web/Ogrenci/Dersler/DersKaynaklari"
NOTIFICATIONS_PATH = "/web/Platform/Notification"
NEWS_PATH = "/web/News/NewsList"
TRANSCRIPT_PATH = "/web/Ogrenci/Transkript"

# Only fixed student-facing GET pages. Navigation never follows action links or submits forms.
SECTION_PATHS = {
    "home": "/web/Main",
    "course_selection": "/web/DersSecimi/DonemDersSecimi",
    "course_resources": RESOURCES_PATH,
    "my_courses": COURSES_PATH,
    "schedules": SCHEDULE_PATH,
    "curriculum": "/web/Ogrenci/Dersler/BolumDersleri",
    "exam_results": RESULTS_PATH,
    "absences": ABSENCE_PATH,
    "transcript": TRANSCRIPT_PATH,
    "document_requests": "/web/Flow/Ogrenci/BelgeTalepListesi",
    "transfer_documents": "/web/Flow/Ogrenci/YatayGecisBelgeBasvurusu",
    "finance_information": "/web/Finans/Sozlesme/info",
    "registration_information": "/web/Ogrenci/Bilgiler/KayitBilgileri",
    "surveys": "/web/Survey",
    "messages": "/web/Message",
    "notifications": NOTIFICATIONS_PATH,
    "news": NEWS_PATH,
}


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


def _tables(page: Page) -> list[dict[str, object]]:
    return page.locator("table").evaluate_all(
        """tables => tables.map(table => ({
          headers: [...table.querySelectorAll('thead th')].map(cell => cell.innerText.trim()),
          rows: [...table.querySelectorAll('tbody tr')].map(row => [...row.querySelectorAll('td')]
            .map(cell => cell.innerText.trim()))
        }))"""
    )


def read_section(section: str, max_chars: int = 20_000) -> dict[str, object]:
    """Read visible text from one fixed EWI menu page without activating page controls."""
    if section not in SECTION_PATHS:
        raise ValueError(f"EWI_SECTION_UNKNOWN: choose one of {', '.join(SECTION_PATHS)}")
    if not 1_000 <= max_chars <= 100_000:
        raise ValueError("EWI_MAX_CHARS_INVALID: use 1000 through 100000")
    path = SECTION_PATHS[section]
    with authenticated_context(EWI_PROFILE_PATH) as context:
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
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, TRANSCRIPT_PATH)
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
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, COURSES_PATH)
        courses: list[dict[str, str | None]] = []
        tables = _tables(page)
        table_elements = page.locator("table")
        for table_index, table in enumerate(tables):
            headers = table["headers"]
            if "Course Code" not in headers or "Course Name" not in headers:
                continue
            indexes = {name: headers.index(name) for name in headers}
            semester = table_elements.nth(table_index).evaluate(
                "table => table.closest('.yoo-card')?.querySelector('.yoo-card-title')"
                "?.innerText.trim() || null"
            )
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
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, SCHEDULE_PATH)
        items = []
        posts = page.locator(".yoo-post.yoo-style3")
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


def get_exam_results() -> list[dict[str, object]]:
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, RESULTS_PATH)
        result = []
        for table in _tables(page):
            headers = table["headers"]
            if "Course Code" in headers and "Letter grade" in headers:
                result.extend({"headers": headers, "values": row} for row in table["rows"])
        return result


def get_absences() -> list[dict[str, object]]:
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, ABSENCE_PATH)
        result = []
        for table in _tables(page):
            headers = table["headers"]
            if "Course Code" in headers and "Total" in headers:
                result.extend({"headers": headers, "values": row} for row in table["rows"])
        return result


def get_course_resources() -> list[dict[str, object]]:
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, RESOURCES_PATH)
        result = []
        tables = _tables(page)
        table_elements = page.locator("table")
        for table_index, table in enumerate(tables):
            headers = table["headers"]
            if "Course Code" in headers and "Resource" in headers:
                semester = table_elements.nth(table_index).evaluate(
                    "table => table.closest('.yoo-card')?.querySelector('.yoo-card-title')"
                    "?.innerText.trim() || null"
                )
                result.extend(
                    {"semester": semester, "headers": headers, "values": row}
                    for row in table["rows"]
                )
        return result


def get_notifications() -> list[dict[str, str | None]]:
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, NOTIFICATIONS_PATH)
        table = next(
            (t for t in _tables(page) if "Notification" in t["headers"] and "Date" in t["headers"]),
            None,
        )
        if table is None:
            raise RuntimeError("EWI_NOTIFICATION_LAYOUT_CHANGED")
        rows = []
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
    with authenticated_context(EWI_PROFILE_PATH) as context:
        page = context.pages[0] if context.pages else context.new_page()
        _page(page, NEWS_PATH)
        result = []
        for link in page.locator('a[href*="/web/News/ReadNews"]').all():
            href = link.get_attribute("href")
            url = urljoin(BASE, href or "")
            if urlparse(url).netloc != urlparse(BASE).netloc:
                continue
            row = link.locator("xpath=ancestor::tr[1]")
            result.append(
                {
                    "title": link.inner_text().strip() or None,
                    "date": row.inner_text().strip().replace(link.inner_text().strip(), "").strip()
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
    with authenticated_context(EWI_PROFILE_PATH) as context:
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
