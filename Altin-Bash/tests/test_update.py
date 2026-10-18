from app.lms.courses import Course
from app.lms.models import CourseSnapshot
from app.services import update
from app.services.scanner import ScanResult
from app.storage import state


def section(source, name, rows):
    return update._section(
        source, name, rows, "2026-10-15T10:00:00+03:00", "https://example.test/source"
    )


def test_timeline_conflicts_unknown_dates_and_cancelled_items():
    sections = [
        section(
            "EWI",
            "schedule",
            [
                {"course_code": "SWE431", "date": "15.10.2026", "time": "10:00-12:00"},
                {"course_code": "IE208", "date": "15.10.2026", "time": "11:00-13:00"},
            ],
        ),
        section(
            "LMS",
            "SWE431:calendar_events",
            [{"course_code": "SWE431", "date": "2026-10-15", "time": "09:00-11:00"}],
        ),
        section(
            "UZEM",
            "calendar",
            [
                {"title": "Unknown date", "date": "Next week"},
                {
                    "title": "Cancelled exam",
                    "status": "Cancelled",
                    "date": "2026-10-15",
                    "time": "10:00-11:00",
                },
            ],
        ),
    ]
    timeline, conflicts = update.timeline_and_conflicts(sections)
    assert len(timeline) == 4
    assert any(item["date_status"] == "Exact date unavailable" for item in timeline)
    assert any(item["status"] == "CONFLICT" for item in conflicts)
    assert any(item["status"] == "POSSIBLE_PORTAL_DISAGREEMENT" for item in conflicts)
    assert update._date("2026-10-14T22:30:00Z") == "2026-10-15"


def test_differences_require_matching_announced_term():
    first = {"course_code": "SWE431", "semester": "Fall 2026/2027", "instructor": "A"}
    second = {**first, "semester": "2026-2027 Fall Semester", "instructor": "B"}
    assert (
        update.course_disagreements(
            [section("LMS", "SWE431:course", [first]), section("EWI", "courses", [second])]
        )[0]["field"]
        == "instructor"
    )
    second["semester"] = "Fall 2025/2026"
    assert (
        update.course_disagreements(
            [section("LMS", "SWE431:course", [first]), section("EWI", "courses", [second])]
        )
        == []
    )


def test_cancellations_keep_evidence_and_alerts_do_not_repeat(tmp_path):
    changes = [
        {"status": "UPDATED", "item": {"title": "Midterm", "status": "Cancelled"}},
        {"status": "NEW", "item": {"title": "Cancellation policy"}},
    ]
    notices = update.cancellation_notices(changes)
    assert notices[0]["status"] == "CANCELLED"
    assert notices[1]["status"] == "CANCELLATION_NOTICE"
    path = tmp_path / "alerts.json"
    assert len(update.new_alerts(notices, path)) == 2
    assert update.new_alerts(notices, path) == []
    assert update.new_alerts([], path) == []
    assert update.new_alerts(notices, path) == []


def test_explicit_timestamp_time_and_possible_date_disagreement():
    rows = [
        section(
            "LMS",
            "SWE431:exams",
            [{"course_code": "SWE431", "title": "Midterm", "date": "2026-11-05T10:00:00+03:00"}],
        ),
        section(
            "EWI", "exams", [{"course_code": "SWE431", "title": "Midterm", "date": "2026-11-06"}]
        ),
    ]
    timeline, conflicts = update.timeline_and_conflicts(rows)
    assert timeline[0]["time"] == "10:00"
    assert conflicts[0]["status"] == "POSSIBLE_PORTAL_DATE_DISAGREEMENT"


def test_removal_once_and_failed_section_preserves_prior_state(tmp_path):
    saved = {"version": 1, "sections": {}}
    identity = lambda section, item: item["id"]
    assert state.compare_section(
        saved, "files", [{"id": 1, "title": "Lecture"}], identity, "first"
    )[1]
    changes, _ = state.compare_section(saved, "files", [], identity, "second")
    assert changes[0]["status"] == "REMOVED"
    assert changes[0]["item"]["title"] == "Lecture"
    assert state.compare_section(saved, "files", [], identity, "third")[0] == []


def test_combined_update_isolates_expired_session_and_omits_private(monkeypatch, tmp_path):
    course = Course("SWE431", "Testing", "https://lms.altinbas.edu.tr/course", "Fall 2026/2027")
    snapshot = CourseSnapshot(course, {}, [], [], [], [], "Unavailable", ["CALENDAR_UNAVAILABLE"])
    monkeypatch.setattr(update, "scan_all", lambda: [ScanResult("SWE431", snapshot, [])])

    def ewi_reader(*, include_private):
        assert include_private is False
        return {
            "scanned_at": "2026-10-15T10:00:00+03:00",
            "scan_errors": {},
            "scanned_sections": ["schedule"],
            "baseline_sections": ["schedule"],
            "changes": [],
            "current": {"schedule": []},
        }

    def expired(*, include_private):
        raise RuntimeError("UZEM_SESSION_EXPIRED: manual sign-in required")

    monkeypatch.setattr(update, "ewi_updates", ewi_reader)
    monkeypatch.setattr(update, "uzem_updates", expired)
    monkeypatch.setattr(update, "new_alerts", lambda items: [])
    result = update.university_update()
    assert result["completeness"] == "PARTIAL"
    assert "UZEM" in result["errors"]
    assert all(
        "source" in item and "scanned_at" in item and "source_url" in item
        for item in result["sections"]
    )
    assert "Not requested" in result["private_sections"]

    def broken_alert_state(items):
        raise RuntimeError("STATE_INVALID")

    monkeypatch.setattr(update, "new_alerts", broken_alert_state)
    assert "LOCAL:alerts" in update.university_update()["errors"]
