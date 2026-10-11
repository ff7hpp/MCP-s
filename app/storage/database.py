"""Transactional course state and change detection."""

import hashlib
import json
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import PROJECT_ROOT
from app.lms.models import Announcement, CourseSnapshot

DEFAULT_DB = PROJECT_ROOT / "data" / "state.sqlite"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(*parts: str) -> str:
    value = "\x1f".join(unicodedata.normalize("NFKC", part).strip().casefold() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _announcement_key(db: sqlite3.Connection, url: str) -> str:
    news_id = parse_qs(urlparse(url).query).get("NewsID", [None])[0]
    if news_id and news_id.isdigit():
        for old in db.execute("SELECT key,url FROM announcements"):
            old_id = parse_qs(urlparse(old["url"]).query).get("NewsID", [None])[0]
            if old_id == news_id:
                return str(old["key"])
        return _key("news", news_id)
    return _key("news-url", url)


def _announcement_changed(old: sqlite3.Row, item: Announcement) -> bool:
    old_date = str(old["posted_at"] or "")
    new_date = item.posted_at
    same_date = old_date.startswith(new_date) or new_date.startswith(old_date)
    return old["title"] != item.title or old["content"] != item.content or not same_date


@contextmanager
def connect(path: Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _create_schema(connection)
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _create_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT, semester TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resources (
            key TEXT PRIMARY KEY, course_code TEXT NOT NULL, title TEXT NOT NULL,
            uploader TEXT, created_at TEXT, url TEXT NOT NULL, description TEXT,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            FOREIGN KEY(course_code) REFERENCES courses(code)
        );
        CREATE TABLE IF NOT EXISTS files (
            key TEXT PRIMARY KEY, resource_key TEXT NOT NULL, course_code TEXT NOT NULL,
            name TEXT NOT NULL, size TEXT, created_at TEXT, remote_id TEXT NOT NULL,
            download_url TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            FOREIGN KEY(resource_key) REFERENCES resources(key)
        );
        CREATE TABLE IF NOT EXISTS file_versions (
            file_key TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
            size TEXT, created_at TEXT, remote_id TEXT NOT NULL, download_url TEXT NOT NULL,
            superseded_at TEXT NOT NULL, PRIMARY KEY(file_key, revision)
        );
        CREATE TABLE IF NOT EXISTS announcements (
            key TEXT PRIMARY KEY, course_code TEXT NOT NULL, title TEXT NOT NULL,
            posted_at TEXT, url TEXT NOT NULL, content TEXT,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exams (
            key TEXT PRIMARY KEY, course_code TEXT NOT NULL, details_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS calendar_events (
            key TEXT PRIMARY KEY, course_code TEXT NOT NULL, date TEXT NOT NULL,
            title TEXT NOT NULL, time TEXT, location TEXT,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, course_code TEXT NOT NULL,
            scanned_at TEXT NOT NULL, status TEXT NOT NULL, error TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_changes (
            scan_id INTEGER NOT NULL, course_code TEXT NOT NULL, status TEXT NOT NULL,
            type TEXT NOT NULL, name TEXT NOT NULL,
            FOREIGN KEY(scan_id) REFERENCES scan_history(id)
        );
        """
    )


def save_snapshot(snapshot: CourseSnapshot, path: Path = DEFAULT_DB) -> list[dict[str, str]]:
    """Persist complete metadata scan; return changes after initial baseline."""
    code = snapshot.course.course_code
    now = _now()
    changes: list[dict[str, str]] = []
    with connect(path) as db:
        initial = (
            db.execute(
                "SELECT 1 FROM scan_history WHERE course_code=? AND status='success' LIMIT 1",
                (code,),
            ).fetchone()
            is None
        )
        db.execute(
            """INSERT INTO courses (code,name,url,semester,first_seen_at,last_seen_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET
               name=excluded.name,url=excluded.url,semester=excluded.semester,
               last_seen_at=excluded.last_seen_at""",
            (
                code,
                snapshot.course.course_name,
                snapshot.course.url,
                snapshot.course.semester,
                now,
                now,
            ),
        )
        seen_files: set[str] = set()
        for resource in snapshot.resources:
            resource_key = _key(code, resource.url)
            old_resource = db.execute(
                "SELECT title,uploader,created_at,description FROM resources WHERE key=?",
                (resource_key,),
            ).fetchone()
            if old_resource is None and not initial:
                changes.append(
                    {"status": "NEW", "type": "resource", "course": code, "name": resource.title}
                )
            elif old_resource is not None and (
                old_resource["title"],
                old_resource["uploader"],
                old_resource["created_at"],
                old_resource["description"],
            ) != (
                resource.title,
                resource.uploader,
                resource.created_at,
                resource.description,
            ):
                changes.append(
                    {
                        "status": "UPDATED",
                        "type": "resource",
                        "course": code,
                        "name": resource.title,
                    }
                )
            db.execute(
                """INSERT INTO resources
                   (key,course_code,title,uploader,created_at,url,description,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   title=excluded.title,uploader=excluded.uploader,created_at=excluded.created_at,
                   description=excluded.description,last_seen_at=excluded.last_seen_at""",
                (
                    resource_key,
                    code,
                    resource.title,
                    resource.uploader,
                    resource.created_at,
                    resource.url,
                    resource.description,
                    now,
                    now,
                ),
            )
            for remote in resource.files:
                file_key = _key(code, resource.url, remote.name)
                if file_key in seen_files:
                    raise ValueError(f"DUPLICATE_REMOTE_FILENAME: {remote.name}")
                seen_files.add(file_key)
                old = db.execute("SELECT * FROM files WHERE key=?", (file_key,)).fetchone()
                if old is None:
                    db.execute(
                        """INSERT INTO files
                           (key,resource_key,course_code,name,size,created_at,remote_id,
                            download_url,revision,first_seen_at,last_seen_at)
                           VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
                        (
                            file_key,
                            resource_key,
                            code,
                            remote.name,
                            remote.size,
                            remote.created_at,
                            remote.remote_id,
                            remote.download_url,
                            now,
                            now,
                        ),
                    )
                    if not initial:
                        changes.append(
                            {"status": "NEW", "type": "file", "course": code, "name": remote.name}
                        )
                else:
                    updated = (old["size"], old["created_at"], old["remote_id"]) != (
                        remote.size,
                        remote.created_at,
                        remote.remote_id,
                    )
                    if updated:
                        db.execute(
                            """INSERT INTO file_versions
                               (file_key,revision,name,size,created_at,remote_id,download_url,superseded_at)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                file_key,
                                old["revision"],
                                old["name"],
                                old["size"],
                                old["created_at"],
                                old["remote_id"],
                                old["download_url"],
                                now,
                            ),
                        )
                        changes.append(
                            {
                                "status": "UPDATED",
                                "type": "file",
                                "course": code,
                                "name": remote.name,
                            }
                        )
                    db.execute(
                        """UPDATE files SET name=?,size=?,created_at=?,remote_id=?,download_url=?,
                           revision=revision+?,last_seen_at=? WHERE key=?""",
                        (
                            remote.name,
                            remote.size,
                            remote.created_at,
                            remote.remote_id,
                            remote.download_url,
                            int(updated),
                            now,
                            file_key,
                        ),
                    )
        for announcement in snapshot.announcements:
            key = _announcement_key(db, announcement.url)
            old = db.execute(
                "SELECT title,posted_at,content FROM announcements WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(
                    {
                        "status": "NEW",
                        "type": "announcement",
                        "course": code,
                        "name": announcement.title,
                    }
                )
            elif old is not None and _announcement_changed(old, announcement):
                changes.append(
                    {
                        "status": "UPDATED",
                        "type": "announcement",
                        "course": code,
                        "name": announcement.title,
                    }
                )
            db.execute(
                """INSERT INTO announcements
                   (key,course_code,title,posted_at,url,content,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   title=excluded.title,
                   posted_at=CASE WHEN length(announcements.posted_at)>length(excluded.posted_at)
                     THEN announcements.posted_at ELSE excluded.posted_at END,
                   content=excluded.content,
                   course_code=CASE WHEN announcements.course_code='GLOBAL'
                     THEN excluded.course_code ELSE announcements.course_code END,
                   last_seen_at=excluded.last_seen_at""",
                (
                    key,
                    code,
                    announcement.title,
                    announcement.posted_at,
                    announcement.url,
                    announcement.content,
                    now,
                    now,
                ),
            )
        for event in snapshot.calendar_events:
            key = _key(code, event.date, event.title)
            old = db.execute(
                "SELECT time,location FROM calendar_events WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(
                    {"status": "NEW", "type": "calendar", "course": code, "name": event.title}
                )
            elif old is not None and (old["time"], old["location"]) != (event.time, event.location):
                changes.append(
                    {"status": "UPDATED", "type": "calendar", "course": code, "name": event.title}
                )
            db.execute(
                """INSERT INTO calendar_events
                   (key,course_code,date,title,time,location,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   time=excluded.time,location=excluded.location,last_seen_at=excluded.last_seen_at""",
                (key, code, event.date, event.title, event.time, event.location, now, now),
            )
        for exam in snapshot.exams:
            exam_json = json.dumps(exam, sort_keys=True, ensure_ascii=False)
            key = _key(code, exam.get("id", exam.get("title", exam_json)))
            old = db.execute("SELECT details_json FROM exams WHERE key=?", (key,)).fetchone()
            if old is None and not initial:
                changes.append(
                    {
                        "status": "NEW",
                        "type": "exam",
                        "course": code,
                        "name": exam.get("title", "Exam"),
                    }
                )
            elif old is not None and old["details_json"] != exam_json:
                changes.append(
                    {
                        "status": "UPDATED",
                        "type": "exam",
                        "course": code,
                        "name": exam.get("title", "Exam"),
                    }
                )
            db.execute(
                """INSERT INTO exams (key,course_code,details_json,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   details_json=excluded.details_json,last_seen_at=excluded.last_seen_at""",
                (key, code, exam_json, now, now),
            )
        cursor = db.execute(
            "INSERT INTO scan_history (course_code,scanned_at,status) VALUES (?,?,'success')",
            (code, now),
        )
        db.executemany(
            "INSERT INTO scan_changes (scan_id,course_code,status,type,name) VALUES (?,?,?,?,?)",
            [
                (cursor.lastrowid, code, item["status"], item["type"], item["name"])
                for item in changes
            ],
        )
    return changes


def latest_files(path: Path = DEFAULT_DB) -> list[dict[str, str]]:
    with connect(path) as db:
        rows = db.execute(
            """SELECT f.course_code,f.name,f.size,f.created_at,f.remote_id,f.download_url,
                      f.revision,r.title AS resource_title,r.url AS resource_url
               FROM files f JOIN resources r ON f.resource_key=r.key
               WHERE f.last_seen_at = (
                 SELECT h.scanned_at FROM scan_history h
                 WHERE h.course_code=f.course_code AND h.status='success'
                 ORDER BY h.id DESC LIMIT 1
               )
               ORDER BY f.course_code,f.name"""
        ).fetchall()
        return [dict(row) for row in rows]


def record_failure(course_code: str, error: str, path: Path = DEFAULT_DB) -> None:
    with connect(path) as db:
        db.execute(
            "INSERT INTO scan_history (course_code,scanned_at,status,error) VALUES (?,?,'failed',?)",
            (course_code, _now(), error[:300]),
        )


def get_new_items(path: Path = DEFAULT_DB) -> list[dict[str, str]]:
    """Changes in each course's most recent successful scan."""
    with connect(path) as db:
        rows = db.execute(
            """SELECT c.course_code,c.status,c.type,c.name
               FROM scan_changes c
               WHERE c.scan_id = (
                 SELECT MAX(h.id) FROM scan_history h
                 WHERE h.course_code=c.course_code AND h.status='success'
               ) OR c.scan_id = (
                 SELECT MAX(h.id) FROM scan_history h
                 WHERE h.course_code='GLOBAL' AND h.status='success'
               ) ORDER BY c.course_code,c.type,c.name"""
        ).fetchall()
        return [dict(row) for row in rows]


def get_rows(
    table: str, course_code: str | None = None, path: Path = DEFAULT_DB
) -> list[dict[str, object]]:
    allowed = {"courses", "resources", "files", "announcements", "exams", "calendar_events"}
    if table not in allowed:
        raise ValueError("INVALID_TABLE")
    with connect(path) as db:
        if course_code:
            column = "code" if table == "courses" else "course_code"
            rows = db.execute(
                f"SELECT * FROM {table} WHERE {column}=? ORDER BY rowid", (course_code,)
            ).fetchall()
        else:
            rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        return [dict(row) for row in rows]


def save_dashboard_announcements(
    entries: list[tuple[str, Announcement]], path: Path = DEFAULT_DB
) -> list[dict[str, str]]:
    now = _now()
    changes: list[dict[str, str]] = []
    with connect(path) as db:
        initial = (
            db.execute(
                "SELECT 1 FROM scan_history WHERE course_code='GLOBAL' AND status='success' LIMIT 1"
            ).fetchone()
            is None
        )
        for course_code, announcement in entries:
            key = _announcement_key(db, announcement.url)
            old = db.execute(
                "SELECT title,posted_at,content FROM announcements WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(
                    {
                        "status": "NEW",
                        "type": "announcement",
                        "course": course_code,
                        "name": announcement.title,
                    }
                )
            elif old is not None and _announcement_changed(old, announcement):
                changes.append(
                    {
                        "status": "UPDATED",
                        "type": "announcement",
                        "course": course_code,
                        "name": announcement.title,
                    }
                )
            db.execute(
                """INSERT INTO announcements
                   (key,course_code,title,posted_at,url,content,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   title=excluded.title,
                   posted_at=CASE WHEN length(announcements.posted_at)>length(excluded.posted_at)
                     THEN announcements.posted_at ELSE excluded.posted_at END,
                   content=excluded.content,
                   course_code=CASE WHEN announcements.course_code='GLOBAL'
                     THEN excluded.course_code ELSE announcements.course_code END,
                   last_seen_at=excluded.last_seen_at""",
                (
                    key,
                    course_code,
                    announcement.title,
                    announcement.posted_at,
                    announcement.url,
                    announcement.content,
                    now,
                    now,
                ),
            )
        cursor = db.execute(
            "INSERT INTO scan_history (course_code,scanned_at,status) VALUES ('GLOBAL',?,'success')",
            (now,),
        )
        db.executemany(
            "INSERT INTO scan_changes (scan_id,course_code,status,type,name) VALUES (?,?,?,?,?)",
            [
                (cursor.lastrowid, item["course"], item["status"], item["type"], item["name"])
                for item in changes
            ],
        )
    return changes
