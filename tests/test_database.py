import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.lms.courses import Course
from app.lms.models import Announcement, CourseSnapshot, RemoteFile, Resource
from app.storage import database
from app.storage.database import (
    connect,
    get_new_items,
    latest_files,
    save_dashboard_announcements,
    save_snapshot,
)


def snapshot(files: list[RemoteFile]) -> CourseSnapshot:
    course = Course(
        "SWE431", "SOFTWARE TESTING", "https://lms.altinbas.edu.tr/course?SID=1", "Fall"
    )
    resource = Resource(
        "Material",
        "Instructor",
        "date",
        len(files),
        "https://lms.altinbas.edu.tr/resource?CRID=2",
        files=files,
    )
    return CourseSnapshot(
        course,
        {},
        [resource],
        [Announcement("News", "date", "https://lms.altinbas.edu.tr/news?id=3")],
        [],
        [],
        "October 2026",
    )


def test_baseline_new_and_updated_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(database, "_now", lambda: "2026-10-14T12:00:00+00:00")
    db = tmp_path / "state.sqlite"
    first = RemoteFile(
        "Lecture1.pdf", "100 KB", "2026-10-01", "https://lms.altinbas.edu.tr/download?id=1", "1"
    )
    second = RemoteFile(
        "Lecture2.pdf", "200 KB", "2026-10-02", "https://lms.altinbas.edu.tr/download?id=2", "2"
    )
    assert save_snapshot(snapshot([first]), db) == []
    assert save_snapshot(snapshot([first]), db) == []
    assert save_snapshot(snapshot([first, second]), db) == [
        {"status": "NEW", "type": "file", "course": "SWE431", "name": "Lecture2.pdf"}
    ]
    assert [
        {key: item[key] for key in ("course_code", "status", "type", "name")}
        for item in get_new_items(db)
    ] == [{"course_code": "SWE431", "status": "NEW", "type": "file", "name": "Lecture2.pdf"}]
    updated = replace(first, size="120 KB", remote_id="3")
    assert save_snapshot(snapshot([updated, second]), db) == [
        {"status": "UPDATED", "type": "file", "course": "SWE431", "name": "Lecture1.pdf"}
    ]
    with connect(db) as connection:
        assert (
            connection.execute("SELECT revision FROM files WHERE name='Lecture1.pdf'").fetchone()[0]
            == 2
        )
        assert connection.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 1
    assert save_snapshot(snapshot([updated, second]), db) == []
    pending = get_new_items(db)
    assert [item["status"] for item in pending] == ["NEW", "UPDATED"]
    database.acknowledge_changes(pending[-1]["change_id"], db)
    assert get_new_items(db) == []
    assert len(latest_files(db)) == 2
    assert save_snapshot(snapshot([second]), db) == [
        {"status": "REMOVED", "type": "file", "course": "SWE431", "name": "Lecture1.pdf"}
    ]
    assert [item["name"] for item in latest_files(db)] == ["Lecture2.pdf"]


def test_duplicate_names_rollback(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    first = RemoteFile(
        "Lecture1.pdf", "100 KB", "date", "https://lms.altinbas.edu.tr/download?id=1", "1"
    )
    with pytest.raises(ValueError, match="DUPLICATE_REMOTE_FILENAME"):
        save_snapshot(snapshot([first, replace(first, remote_id="2")]), db)
    with connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM scan_history").fetchone()[0] == 0


def test_existing_file_rows_migrate_to_scan_ids(tmp_path: Path) -> None:
    db = tmp_path / "old.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """CREATE TABLE files (
                 key TEXT PRIMARY KEY, resource_key TEXT, course_code TEXT, name TEXT,
                 size TEXT, created_at TEXT, remote_id TEXT, download_url TEXT,
                 revision INTEGER, first_seen_at TEXT, last_seen_at TEXT
               );
               CREATE TABLE resources (key TEXT PRIMARY KEY, title TEXT, url TEXT);
               CREATE TABLE scan_history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, course_code TEXT,
                 scanned_at TEXT, status TEXT, error TEXT
               );
               INSERT INTO resources VALUES ('r', 'Material', 'https://example.test/r');
               INSERT INTO scan_history (course_code,scanned_at,status)
                 VALUES ('SWE431','2026-10-14T12:00:00','success');
               INSERT INTO files VALUES (
                 'f','r','SWE431','Lecture.pdf','1 KB',NULL,'1','https://example.test/f',
                 1,'2026-10-14T12:00:00','2026-10-14T12:00:00'
               );"""
        )
    with connect(db):
        pass
    assert [row["name"] for row in latest_files(db)] == ["Lecture.pdf"]
    with connect(db) as connection:
        assert connection.execute("SELECT last_seen_scan_id FROM files").fetchone()[0] == 1


def test_dashboard_news_deduplicates_course_news(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    course = Course("IE208", "ECONOMICS", "https://lms.altinbas.edu.tr/course?SID=1", "Fall")
    course_news = Announcement(
        "Clarification",
        "30.09.2026 11:20",
        "https://lms.altinbas.edu.tr/web/Uzem/News/ReadNews?NewsID=6455&SID=1",
        "Content",
    )
    state = CourseSnapshot(course, {}, [], [course_news], [], [], "October 2026")
    assert save_snapshot(state, db) == []
    dashboard_news = replace(
        course_news,
        posted_at="30.09.2026",
        url="https://lms.altinbas.edu.tr/web/Uzem/News/ReadNews?NewsID=6455",
    )
    assert save_dashboard_announcements([("IE208", dashboard_news)], db) == []
    with connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
        assert (
            connection.execute("SELECT posted_at FROM announcements").fetchone()[0]
            == "30.09.2026 11:20"
        )


def test_new_term_never_falls_back_to_legacy_previous_term_keys(tmp_path):
    path = tmp_path / "state.sqlite"
    remote = RemoteFile("Lecture.pdf", "100 B", "date", "https://example.test/download", "1")
    old = snapshot([remote])
    save_snapshot(old, path)
    resource = old.resources[0]
    with sqlite3.connect(path) as db:
        old_key = db.execute("SELECT key FROM resources").fetchone()[0]
        legacy = database._key(old.course.course_code, resource.url)
        db.execute("UPDATE resources SET key=? WHERE key=?", (legacy, old_key))
        db.execute(
            "UPDATE files SET resource_key=?,key=?",
            (legacy, database._key(old.course.course_code, resource.url, remote.name)),
        )
    new = replace(old, course=replace(old.course, semester="Spring 2026/2027"))
    assert save_snapshot(new, path) == []
    assert save_snapshot(new, path) == []
    assert len(latest_files(path)) == 1


def test_stored_reads_do_not_initialize_or_migrate(tmp_path):
    path = tmp_path / "missing.sqlite"
    assert database.get_rows("courses", path=path) == []
    assert not path.exists()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE old_data (value TEXT)")
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="STATE_MIGRATION_REQUIRED"):
        database.get_rows("courses", path=path)
    assert path.read_bytes() == original


def test_section_failure_preserves_calendar_and_term_change_clears_current_scope(tmp_path):
    from app.lms.models import CalendarEvent

    path = tmp_path / "state.sqlite"
    first = replace(
        snapshot([]), calendar_events=[CalendarEvent("2026-10-16", "Class", "09:00-10:00")]
    )
    save_snapshot(first, path)
    failed = replace(first, calendar_events=[], warnings=["CALENDAR_UNAVAILABLE"])
    save_snapshot(failed, path)
    result = database.stored_section("calendar_events", path=path)
    assert result["items"][0]["title"] == "Class"
    assert result["sections"][0]["freshness"] == "STALE"
    assert result["completeness"] == "PARTIAL"
    new_term = replace(failed, course=replace(failed.course, semester="Spring 2026/2027"))
    save_snapshot(new_term, path)
    assert database.stored_section("calendar_events", path=path)["items"] == []


def test_announcements_reconcile_current_scope_without_deleting_history(tmp_path):
    path = tmp_path / "state.sqlite"
    first = snapshot([])
    save_snapshot(first, path)
    assert database.stored_section("announcements", path=path)["items"]
    changes = save_snapshot(replace(first, announcements=[]), path)
    assert any(item["status"] == "REMOVED" and item["type"] == "announcement" for item in changes)
    assert not any(
        item["type"] == "announcement"
        for item in save_snapshot(replace(first, announcements=[]), path)
    )
    assert database.stored_section("announcements", path=path)["items"] == []
    with connect(path, readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1


def test_failed_resource_preserves_siblings_and_removal_waits_for_complete_scan(tmp_path):
    path = tmp_path / "state.sqlite"
    file = RemoteFile("one.pdf", "100 B", "date", "https://example.test/file", "1")
    first = snapshot([file])
    second_resource = replace(
        first.resources[0],
        title="Second",
        url="https://example.test/resource?CRID=3",
        files=[replace(file, name="two.pdf", remote_id="2")],
    )
    first = replace(first, resources=[first.resources[0], second_resource])
    save_snapshot(first, path)
    partial = replace(
        first,
        resources=[
            replace(first.resources[0], files=[], detail_error="Detail failed"),
            second_resource,
        ],
        section_errors={"resources:one": "Detail failed", "files": "Partial resources"},
    )
    assert not any(change["status"] == "REMOVED" for change in save_snapshot(partial, path))
    assert len(database.stored_section("files", path=path)["items"]) == 2
    changes = save_snapshot(replace(first, resources=[second_resource]), path)
    assert any(
        change["type"] == "file" and change["name"] == "one.pdf" and change["status"] == "REMOVED"
        for change in changes
    )


def test_calendar_remote_ids_keep_same_day_meetings_and_detect_reschedule(tmp_path):
    from app.lms.models import CalendarEvent

    path = tmp_path / "state.sqlite"
    first = replace(
        snapshot([]),
        calendar_events=[
            CalendarEvent("2026-10-16", "Course", "09:00-10:00", "A", "1"),
            CalendarEvent("2026-10-16", "Course", "14:00-15:00", "B", "2"),
        ],
        calendar_scope="Embedded LMS calendar JSON; explicit fixture scope",
    )
    save_snapshot(first, path)
    assert len(database.get_rows("calendar_events", path=path)) == 2
    moved = replace(
        first,
        calendar_events=[
            replace(first.calendar_events[0], date="2026-10-17"),
            first.calendar_events[1],
        ],
    )
    changes = save_snapshot(moved, path)
    assert any(item["type"] == "calendar" and item["status"] == "UPDATED" for item in changes)
    assert {item["date"] for item in database.get_rows("calendar_events", path=path)} == {
        "2026-10-16",
        "2026-10-17",
    }
    removed = save_snapshot(replace(moved, calendar_events=[]), path)
    assert (
        len(
            [item for item in removed if item["type"] == "calendar" and item["status"] == "REMOVED"]
        )
        == 2
    )
    assert not any(
        item["type"] == "calendar"
        for item in save_snapshot(replace(moved, calendar_events=[]), path)
    )
