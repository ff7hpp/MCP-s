"""A broken LMS calendar must not hide downloadable course materials."""

from unittest.mock import MagicMock

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.lms import scanner
from app.lms.courses import Course
from app.lms.models import RemoteFile, Resource


def test_calendar_timeout_keeps_course_files(monkeypatch) -> None:
    page = MagicMock()
    info = MagicMock()
    info.locator.return_value.filter.return_value.locator.return_value.first.inner_text.return_value = "IE208"
    resource = Resource(
        title="Study slides",
        uploader="Instructor",
        created_at="2026-10-14",
        file_count=1,
        url="https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersKaynaklari",
        files=[RemoteFile("slides.pdf", "100 KB", "2026-10-14", "https://example.org", "1")],
    )
    monkeypatch.setattr(scanner, "_card", lambda _page, _title: info)
    monkeypatch.setattr(scanner, "_course_hours", lambda _page: {})
    monkeypatch.setattr(scanner, "_resources", lambda _page, _course, _errors=None: [resource])
    monkeypatch.setattr(scanner, "_exams", lambda _page: [])
    monkeypatch.setattr(scanner, "_resource_details", lambda _page, _course, item: item)

    def unavailable_calendar(_page):
        raise PlaywrightTimeoutError("Calendar did not initialize")

    monkeypatch.setattr(scanner, "_calendar", unavailable_calendar)
    course = Course(
        "IE208",
        "Engineering Economics and Finance",
        "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=1",
        "Fall 2026/2027",
    )

    snapshot = scanner.scan_course_page(page, course)

    assert snapshot.resources[0].files[0].name == "slides.pdf"
    assert snapshot.calendar_scope == "Unavailable"
    assert snapshot.warnings == ["CALENDAR_UNAVAILABLE: LMS calendar did not load"]
