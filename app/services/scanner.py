"""Sequential scans with per-course failure isolation."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.config import LMS_URL
from app.lms.announcements import dashboard_announcements
from app.lms.browser import authenticated_context
from app.lms.courses import discover_courses
from app.lms.models import CourseSnapshot
from app.lms.readonly import assert_readonly
from app.lms.scanner import scan_course, scan_course_page
from app.lms.sections import catalogue, notifications
from app.storage.database import (
    record_failure,
    save_dashboard_announcements,
    save_global_section,
    save_snapshot,
)
from app.storage.state import serialized


@dataclass
class ScanResult:
    code: str
    snapshot: CourseSnapshot | None
    changes: list[dict[str, object]]
    error: str | None = None
    scanned_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dashboard_items: list[dict] = field(default_factory=list)
    global_sections: dict[str, list[dict]] = field(default_factory=dict)
    section_errors: dict[str, str] = field(default_factory=dict)

    @property
    def errors(self):
        return {
            **({"course": self.error} if self.error else {}),
            **self.section_errors,
            **(self.snapshot.section_errors if self.snapshot else {}),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "course_code": self.code,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "changes": self.changes,
            "error": self.error,
            "errors": self.errors,
            "completeness": "PARTIAL" if self.errors else "COMPLETE_IN_SCANNED_SCOPES",
            "source": "LMS",
            "scanned_at": self.scanned_at,
            "dashboard_items": self.dashboard_items,
            "global_sections": self.global_sections,
            "section_errors": self.section_errors,
        }


def scan_errors(results):
    errors = {}
    for result in results:
        if result.error:
            errors[result.code] = result.error
        errors.update(
            {
                f"{result.code}:{key}": value
                for key, value in result.errors.items()
                if key != "course"
            }
        )
    return errors


@serialized
def scan_one(course_code: str) -> ScanResult:
    snapshot = scan_course(course_code)
    changes = save_snapshot(snapshot)
    return ScanResult(snapshot.course.course_code, snapshot, changes)


@serialized
def scan_all() -> list[ScanResult]:
    results: list[ScanResult] = []
    try:
        with authenticated_context() as context:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:  # noqa: BLE001 - convert unexpected browser failures to scan results
                error = (
                    f"LMS_NAVIGATION_FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
                )
                record_failure("GLOBAL", error)
                return [ScanResult("GLOBAL", None, [], error)]
            try:
                errors = {}
                dashboard = dashboard_announcements(page, errors)
                assert_readonly(context)
                changes = save_dashboard_announcements(dashboard, errors=errors)
                results.append(
                    ScanResult(
                        "GLOBAL",
                        None,
                        changes,
                        dashboard_items=[
                            {"course_code": code, **asdict(item)} for code, item in dashboard
                        ],
                        section_errors=errors,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - course scans can continue after dashboard failure
                error = (
                    f"DASHBOARD_SCAN_FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
                )
                record_failure("GLOBAL", error)
                results.append(ScanResult("GLOBAL", None, [], error))
            try:
                items = notifications(page)
                assert_readonly(context)
                changes = save_global_section("notifications", items)
                results.append(
                    ScanResult("GLOBAL", None, changes, global_sections={"notifications": items})
                )
            except Exception as exc:  # noqa: BLE001 - isolate notification source
                error = f"NOTIFICATION_SCAN_FAILED: {type(exc).__name__}"
                save_global_section("notifications", [], {"notifications": error})
                results.append(
                    ScanResult(
                        "GLOBAL",
                        None,
                        [],
                        global_sections={"notifications": []},
                        section_errors={"notifications": error},
                    )
                )
            try:
                followed, page_number = [], 1
                while True:
                    result = catalogue(page, followed_only=True, page_number=page_number)
                    followed.extend(result["items"])
                    if not result["has_more"]:
                        break
                    page_number += 1
                    if page_number > 20:
                        raise RuntimeError("CATALOGUE_PAGINATION_LIMIT")
                changes = save_global_section("catalogue", followed)
                results.append(
                    ScanResult("GLOBAL", None, changes, global_sections={"catalogue": followed})
                )
            except Exception as exc:  # noqa: BLE001 - catalogue is separate from enrollment
                error = f"CATALOGUE_SCAN_FAILED: {type(exc).__name__}"
                save_global_section("catalogue", [], {"catalogue": error})
                results.append(
                    ScanResult(
                        "GLOBAL",
                        None,
                        [],
                        global_sections={"catalogue": []},
                        section_errors={"catalogue": error},
                    )
                )
            page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
            try:
                courses = discover_courses(page)
            except Exception as exc:  # noqa: BLE001 - discovery must not hide diagnostics
                error = f"COURSE_DISCOVERY_FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
                record_failure("GLOBAL", error)
                results.append(ScanResult("GLOBAL", None, [], error))
                return results
            for course in courses:
                try:
                    snapshot = scan_course_page(page, course)
                    assert_readonly(context)
                    changes = save_snapshot(snapshot)
                    results.append(ScanResult(course.course_code, snapshot, changes))
                except Exception as exc:  # noqa: BLE001 - isolate one broken course
                    error = f"COURSE_SCAN_FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
                    record_failure(course.course_code, error)
                    results.append(ScanResult(course.course_code, None, [], error))
    except Exception as exc:  # noqa: BLE001 - MCP must return a diagnostic instead of crashing
        error = f"LMS_SCAN_FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
        record_failure("GLOBAL", error)
        results.append(ScanResult("GLOBAL", None, [], error))
    return results
