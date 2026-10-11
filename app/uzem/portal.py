"""Read enrolled courses and academic pages from the legacy UZEM Moodle site."""

from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error, Page

from app.config import UZEM_PROFILE_PATH, UZEM_URL
from app.lms.browser import LoginError, authenticated_uzem_context, is_uzem_authenticated

HOST = "uzem.altinbas.edu.tr"


def _safe_url(value: str | None, path: str | None = None) -> str | None:
    """Expose only ordinary HTTPS links on the UZEM host; never expose sesskey URLs."""
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        return None
    if path and parsed.path != path:
        return None
    if "sesskey" in parse_qs(parsed.query):
        return None
    return value


def _open(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if not is_uzem_authenticated(page):
        raise LoginError("UZEM_SESSION_EXPIRED: run `python -m app.cli uzem-login`")


def _course_cards(page: Page) -> list[dict[str, object]]:
    page.locator('[data-region="course-content"]').first.wait_for(timeout=15000)
    courses = []
    seen = set()
    for card in page.locator('[data-region="course-content"][data-course-id]').all():
        course_id = card.get_attribute("data-course-id") or ""
        if not course_id.isdecimal() or course_id in seen:
            continue
        seen.add(course_id)
        title = card.locator("a.coursename .multiline").first.inner_text().strip()
        category = (
            card.locator(".categoryname").first.inner_text().strip()
            if card.locator(".categoryname").count()
            else None
        )
        progress = (
            card.locator(".progress-text span:not(.sr-only)").first.inner_text().strip()
            if card.locator(".progress-text span:not(.sr-only)").count()
            else None
        )
        courses.append(
            {
                "id": int(course_id),
                "name": title,
                "category": category,
                "progress_percent": int(progress) if progress and progress.isdecimal() else None,
                "url": f"https://{HOST}/course/view.php?id={course_id}",
            }
        )
    return courses


def _enrolled(page: Page) -> list[dict[str, object]]:
    _open(page, UZEM_URL)
    return _course_cards(page)


def status() -> dict[str, object]:
    """Local session presence only; live calls verify portal authentication."""
    return {
        "session_profile_present": UZEM_PROFILE_PATH.is_dir(),
        "session_cookie_present": (UZEM_PROFILE_PATH / "session.json").is_file(),
        "portal": UZEM_URL,
    }


def list_courses() -> list[dict[str, object]]:
    with authenticated_uzem_context() as context:
        page = context.new_page()
        return _enrolled(page)


def _course(page: Page, course: dict[str, object]) -> dict[str, object]:
    _open(page, str(course["url"]))
    sections = []
    for section in page.locator("li.course-section").all():
        name = (
            section.locator(".sectionname").first.inner_text().strip()
            if section.locator(".sectionname").count()
            else ""
        )
        activities = []
        for activity in section.locator("li.activity[data-id]").all():
            activity_id = activity.get_attribute("data-id") or ""
            classes = (activity.get_attribute("class") or "").split()
            kind = next(
                (part.removeprefix("modtype_") for part in classes if part.startswith("modtype_")),
                "unknown",
            )
            link = activity.locator(".activityname a[href]").first
            title = (
                activity.locator(".instancename").first.inner_text().splitlines()[0].strip()
                if activity.locator(".instancename").count()
                else ""
            )
            url = _safe_url(link.get_attribute("href")) if link.count() else None
            activities.append(
                {
                    "id": int(activity_id) if activity_id.isdecimal() else None,
                    "type": kind,
                    "title": title,
                    "url": url,
                }
            )
        sections.append({"title": name, "activities": activities})
    return {"course": course, "sections": sections}


def get_course(course_id: int) -> dict[str, object]:
    if course_id <= 0:
        raise ValueError("course_id must be positive")
    with authenticated_uzem_context() as context:
        page = context.new_page()
        course = next((item for item in _enrolled(page) if item["id"] == course_id), None)
        if course is None:
            raise ValueError("Course is not in the enrolled UZEM course list")
        return _course(page, course)


def _notifications(page: Page) -> list[dict[str, object]]:
    _open(page, f"https://{HOST}/message/output/popup/notifications.php")
    area = page.locator('[data-region="notification-area"]')
    area.wait_for(timeout=15000)
    page.wait_for_function(
        """() => {
      const area = document.querySelector('[data-region="notification-area"]');
      return area && !area.classList.contains('loading');
    }""",
        timeout=10000,
    )
    results = []
    for item in area.locator(
        '[data-region="control-area"] [data-region="notification-item-container"]'
    ).all():
        link = item.locator("a[href]").first
        date = item.locator("time").first
        results.append(
            {
                "title": item.inner_text().strip(),
                "date": date.get_attribute("datetime") if date.count() else None,
                "url": _safe_url(link.get_attribute("href")) if link.count() else None,
            }
        )
    return results


def get_notifications() -> list[dict[str, object]]:
    with authenticated_uzem_context() as context:
        return _notifications(context.new_page())


def _calendar(page: Page) -> list[dict[str, object]]:
    _open(page, f"https://{HOST}/calendar/view.php")
    wrapper = page.locator('.calendarwrapper[data-view="upcoming"]')
    wrapper.wait_for(timeout=15000)
    events = []
    for item in wrapper.locator(".eventlist [data-event-id], .eventlist .event").all():
        link = item.locator('a[href*="/calendar/"]').first
        time = item.locator("time").first
        events.append(
            {
                "title": item.inner_text().strip(),
                "date": time.get_attribute("datetime") if time.count() else None,
                "url": _safe_url(link.get_attribute("href")) if link.count() else None,
            }
        )
    return events


def get_calendar() -> list[dict[str, object]]:
    with authenticated_uzem_context() as context:
        return _calendar(context.new_page())


def _grades(page: Page, courses: list[dict[str, object]]) -> list[dict[str, object]]:
    results = []
    for course in courses:
        _open(page, f"https://{HOST}/grade/report/user/index.php?id={course['id']}")
        table = page.locator("table.user-grade")
        rows = []
        if table.count():
            for row in table.locator("tr").all()[1:]:
                cells = [cell.strip() for cell in row.locator("th, td").all_inner_texts()]
                if cells and cells[0] and len(cells) >= 3:
                    rows.append(
                        {
                            "item": cells[0],
                            "weight": cells[1],
                            "grade": cells[2],
                            "range": cells[3] if len(cells) > 3 else None,
                            "percentage": cells[4] if len(cells) > 4 else None,
                        }
                    )
        results.append({"course_id": course["id"], "course_name": course["name"], "rows": rows})
    return results


def get_grades() -> list[dict[str, object]]:
    with authenticated_uzem_context() as context:
        page = context.new_page()
        return _grades(page, _enrolled(page))


def _announcements(
    page: Page, course: dict[str, object], activities: list[dict[str, object]]
) -> list[dict[str, object]]:
    results = []
    for activity in activities:
        if activity["type"] != "forum" or not activity["url"]:
            continue
        _open(page, str(activity["url"]))
        for row in page.locator('tr[data-region="discussion-list-item"]').all():
            link = row.locator('.topic a[href*="/mod/forum/discuss.php"]').first
            if not link.count():
                continue
            time = row.locator("time").first
            results.append(
                {
                    "course_id": course["id"],
                    "forum": activity["title"],
                    "title": link.inner_text().strip(),
                    "date": time.get_attribute("datetime") if time.count() else None,
                    "url": _safe_url(link.get_attribute("href"), "/mod/forum/discuss.php"),
                }
            )
    return results


def get_announcements(course_id: int) -> list[dict[str, object]]:
    if course_id <= 0:
        raise ValueError("course_id must be positive")
    with authenticated_uzem_context() as context:
        page = context.new_page()
        course = next((item for item in _enrolled(page) if item["id"] == course_id), None)
        if course is None:
            raise ValueError("Course is not in the enrolled UZEM course list")
        snapshot = _course(page, course)
        activities = [
            activity for section in snapshot["sections"] for activity in section["activities"]
        ]
        return _announcements(page, course, activities)


def scan_all() -> dict[str, object]:
    """Read all supported UZEM sections; report individual failures."""
    with authenticated_uzem_context() as context:
        page = context.new_page()
        courses = _enrolled(page)
        result: dict[str, object] = {
            "courses": courses,
            "course_details": [],
            "announcements": [],
            "notifications": [],
            "calendar": [],
            "grades": [],
            "scan_errors": {},
        }
        for course in courses:
            try:
                detail = _course(page, course)
                result["course_details"].append(detail)
                activities = [
                    activity for section in detail["sections"] for activity in section["activities"]
                ]
                result["announcements"].extend(_announcements(page, course, activities))
            except (LoginError, RuntimeError, ValueError, Error) as exc:
                result["scan_errors"][f"course:{course['id']}"] = str(exc).splitlines()[0]
        for name, reader in (("notifications", _notifications), ("calendar", _calendar)):
            try:
                result[name] = reader(page)
            except (LoginError, RuntimeError, ValueError, Error) as exc:
                result["scan_errors"][name] = str(exc).splitlines()[0]
        try:
            result["grades"] = _grades(page, courses)
        except (LoginError, RuntimeError, ValueError, Error) as exc:
            result["scan_errors"]["grades"] = str(exc).splitlines()[0]
        return result
