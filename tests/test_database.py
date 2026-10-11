from dataclasses import replace
from pathlib import Path

import pytest

from app.lms.courses import Course
from app.lms.models import Announcement, CourseSnapshot, RemoteFile, Resource
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


def test_baseline_new_and_updated_files(tmp_path: Path) -> None:
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
    assert get_new_items(db) == [
        {"course_code": "SWE431", "status": "NEW", "type": "file", "name": "Lecture2.pdf"}
    ]
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
    assert get_new_items(db) == []
    assert len(latest_files(db)) == 2
    assert save_snapshot(snapshot([second]), db) == []
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
