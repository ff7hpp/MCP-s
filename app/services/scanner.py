"""Sequential scans with per-course failure isolation."""

from dataclasses import dataclass

from playwright.sync_api import Error

from app.config import LMS_URL
from app.lms.announcements import dashboard_announcements
from app.lms.browser import authenticated_context
from app.lms.courses import discover_courses
from app.lms.models import CourseSnapshot
from app.lms.scanner import scan_course, scan_course_page
from app.storage.database import record_failure, save_dashboard_announcements, save_snapshot


@dataclass
class ScanResult:
    code: str
    snapshot: CourseSnapshot | None
    changes: list[dict[str, str]]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "course_code": self.code,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "changes": self.changes,
            "error": self.error,
        }


def scan_one(course_code: str) -> ScanResult:
    snapshot = scan_course(course_code)
    changes = save_snapshot(snapshot)
    return ScanResult(snapshot.course.course_code, snapshot, changes)


def scan_all() -> list[ScanResult]:
    results: list[ScanResult] = []
    with authenticated_context() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            dashboard = dashboard_announcements(page)
            changes = save_dashboard_announcements(dashboard)
            results.append(ScanResult("GLOBAL", None, changes))
        except (RuntimeError, ValueError, Error) as exc:
            error = str(exc).splitlines()[0][:300]
            record_failure("GLOBAL", error)
            results.append(ScanResult("GLOBAL", None, [], error))
        page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
        courses = discover_courses(page)
        for course in courses:
            try:
                snapshot = scan_course_page(page, course)
                changes = save_snapshot(snapshot)
                results.append(ScanResult(course.course_code, snapshot, changes))
            except (RuntimeError, ValueError, Error) as exc:
                error = str(exc).splitlines()[0][:300]
                record_failure(course.course_code, error)
                results.append(ScanResult(course.course_code, None, [], error))
    return results
