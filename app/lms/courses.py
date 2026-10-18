"""Dynamic course discovery from the authenticated My Courses table."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

from playwright.sync_api import Page

from app.config import LMS_URL
from app.lms.auth import is_authenticated
from app.lms.browser import LoginError, authenticated_context

COURSE_DETAIL_PATH = "/web/Uzem/Ogrenci/Dersler/DersDetay"
COURSE_LIST_PATH = "/web/Uzem/Ogrenci/Dersler/Derslerim"
SID_PATTERN = re.compile(r"DersDetay\?SID=(\d+)")


@dataclass(frozen=True)
class Course:
    course_code: str
    course_name: str
    url: str | None
    semester: str
    section: str | None = None
    instructor: str | None = None
    credit: str | None = None
    ects: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def parse_course_row(cells: list[str], onclick: str | None, semester: str) -> Course:
    if len(cells) < 2 or not cells[0].strip() or not cells[1].strip():
        raise ValueError("COURSE_ROW_INVALID: code or name missing")
    match = SID_PATTERN.search(onclick or "")
    url = urljoin(LMS_URL, f"{COURSE_DETAIL_PATH}?SID={match.group(1)}") if match else None
    padded = [cell.strip() for cell in cells] + [None] * 6
    return Course(
        course_code=padded[0],
        course_name=padded[1],
        url=url,
        semester=semester,
        section=padded[2],
        instructor=padded[3],
        credit=padded[4],
        ects=padded[5],
    )


def discover_courses(page: Page) -> list[Course]:
    if not is_authenticated(page):
        raise LoginError("SESSION_EXPIRED: run `python -m app.cli login` and sign in manually")
    nav = page.locator(f'a[href*="{COURSE_LIST_PATH}"]').first
    if not nav.is_visible():
        raise RuntimeError("COURSES_PAGE_NOT_FOUND: My Courses link absent")
    nav.click()
    page.wait_for_load_state("domcontentloaded")
    tables = page.locator("table").filter(has=page.get_by_role("columnheader", name="Course Code"))
    if tables.count() != 1:
        raise RuntimeError("COURSES_PAGE_NOT_FOUND: course table missing or ambiguous")
    table = tables.first
    headers = [h.strip() for h in table.locator("thead th").all_inner_texts()]
    if headers[:2] != ["Course Code", "Course Name"]:
        raise RuntimeError("COURSES_PAGE_NOT_FOUND: course columns changed")
    semester = next(
        (
            title.strip()
            for title in page.locator("h1,h2,h3").all_inner_texts()
            if "Semester" in title
        ),
        "Unknown",
    )
    courses: list[Course] = []
    for row in table.locator("tbody tr").all():
        cells = row.locator("td").all_inner_texts()
        if not cells:
            continue
        courses.append(parse_course_row(cells, row.get_attribute("onclick"), semester))
    return courses


def list_courses() -> list[Course]:
    with authenticated_context() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
        return discover_courses(page)
