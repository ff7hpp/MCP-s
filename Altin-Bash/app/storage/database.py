"""Transactional course state and change detection."""

import hashlib
import json
import os
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import LMS_URL, PROJECT_ROOT
from app.errors import ActionableError
from app.lms.models import Announcement, CourseSnapshot
from app.storage.state import backup_file, operation_lock, serialized

DEFAULT_DB = PROJECT_ROOT / "data" / "state.sqlite"
SCHEMA_VERSION = 3
ACADEMIC_SECTIONS = {"assignments", "notifications", "live_lessons", "study_links", "catalogue"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(*parts: str) -> str:
    value = "\x1f".join(unicodedata.normalize("NFKC", part).strip().casefold() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _current_key(db, table, term_key, legacy_key, previous_scan_id):
    if db.execute(f"SELECT 1 FROM {table} WHERE key=?", (term_key,)).fetchone():
        return term_key
    if (
        previous_scan_id is not None
        and db.execute(
            f"SELECT 1 FROM {table} WHERE key=? AND last_seen_scan_id=?",
            (legacy_key, previous_scan_id),
        ).fetchone()
    ):
        return legacy_key
    return term_key


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


def _announcement_change(status, code, item):
    return {
        "status": status,
        "type": "announcement",
        "course": code,
        "name": item.title,
        "source_url": item.url,
        "remote_id": parse_qs(urlparse(item.url).query).get("NewsID", [None])[0],
        "item": asdict(item),
    }


@contextmanager
def connect(path: Path = DEFAULT_DB, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    with operation_lock():
        if readonly:
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise ActionableError(
                        "STATE_MIGRATION_REQUIRED: run an authorized scan before reading stored data"
                    )
                yield connection
            finally:
                connection.close()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            existing_tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema_version > SCHEMA_VERSION:
                raise ValueError(
                    "STATE_VERSION_UNSUPPORTED: use a compatible application; original preserved"
                )
            migrating = any(
                table in existing_tables
                and "last_seen_scan_id"
                not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                for table in ("files", "resources", "exams", "calendar_events")
            )
            if migrating or (existing_tables and schema_version < SCHEMA_VERSION):
                directory = path.parent / "backups"
                directory.mkdir(exist_ok=True)
                handle, backup = tempfile.mkstemp(
                    prefix=f"{path.name}.migration-", suffix=".sqlite", dir=directory
                )
                os.close(handle)
                with closing(sqlite3.connect(backup)) as target:
                    connection.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("BACKUP_INTEGRITY_FAILED")
                for old in sorted(
                    directory.glob(f"{path.name}.migration-*.sqlite"),
                    key=lambda p: p.stat().st_mtime_ns,
                )[:-5]:
                    old.unlink()
            _create_schema(connection)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
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
            last_seen_scan_id INTEGER,
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
        CREATE TABLE IF NOT EXISTS section_scans (
            course_code TEXT NOT NULL, section TEXT NOT NULL, attempted_at TEXT NOT NULL,
            last_successful_at TEXT, last_successful_scan_id INTEGER, error TEXT, scope TEXT,
            PRIMARY KEY(course_code,section)
        );
        CREATE TABLE IF NOT EXISTS section_members (
            course_code TEXT NOT NULL, section TEXT NOT NULL, scan_id INTEGER NOT NULL,
            item_key TEXT NOT NULL, PRIMARY KEY(course_code,section,scan_id,item_key)
        );
        CREATE INDEX IF NOT EXISTS scan_history_course_status ON scan_history(course_code,status,id);
        CREATE TABLE IF NOT EXISTS academic_items (
            key TEXT PRIMARY KEY, course_code TEXT NOT NULL, section TEXT NOT NULL,
            title TEXT NOT NULL, details_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            last_seen_scan_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS change_acknowledgements (
            consumer TEXT PRIMARY KEY, through_change_id INTEGER NOT NULL
        );
        """
    )
    additions = {
        "calendar_events": {
            "remote_id": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "event_type": "TEXT NOT NULL DEFAULT ''",
            "end_date": "TEXT NOT NULL DEFAULT ''",
        },
        "section_scans": {"last_attempt_scan_id": "INTEGER"},
        "scan_changes": {"remote_id": "TEXT", "source_url": "TEXT"},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        if table == "calendar_events" and "description" not in existing and "location" in existing:
            db.execute("UPDATE calendar_events SET description=COALESCE(location,''),location=''")
    if "last_seen_scan_id" not in {row[1] for row in db.execute("PRAGMA table_info(files)")}:
        db.execute("ALTER TABLE files ADD COLUMN last_seen_scan_id INTEGER")
        db.execute(
            """UPDATE files SET last_seen_scan_id = (
                 SELECT MAX(h.id) FROM scan_history h
                 WHERE h.course_code=files.course_code AND h.status='success'
                   AND h.scanned_at=files.last_seen_at
               ) WHERE (
                 SELECT COUNT(*) FROM scan_history h
                 WHERE h.course_code=files.course_code AND h.status='success'
                   AND h.scanned_at=files.last_seen_at
               ) = 1"""
        )

    for table in ("resources", "exams", "calendar_events"):
        if "last_seen_scan_id" not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN last_seen_scan_id INTEGER")
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if {"course_code", "last_seen_at"} <= columns:
                db.execute(f"""UPDATE {table} SET last_seen_scan_id=(SELECT MAX(h.id) FROM scan_history h
                    WHERE h.course_code={table}.course_code AND h.status='success' AND h.scanned_at={table}.last_seen_at)
                    WHERE (SELECT COUNT(*) FROM scan_history h WHERE h.course_code={table}.course_code
                    AND h.status='success' AND h.scanned_at={table}.last_seen_at)=1""")


@serialized
def recover_database(path: Path, backup: Path) -> None:
    """Restore only a checked local backup; retain the original even if corrupt."""
    if backup.resolve().parent != (path.parent / "backups").resolve():
        raise ValueError("BACKUP_OUTSIDE_STATE_DIRECTORY")
    if Path(str(path) + "-wal").exists():
        raise ValueError("STATE_BUSY: close SQLite clients and checkpoint WAL before recovery")
    original = sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
    handle, name = tempfile.mkstemp(prefix="restore-", suffix=".sqlite", dir=path.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        if original.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("BACKUP_INTEGRITY_FAILED")
        with closing(sqlite3.connect(temporary)) as target:
            original.backup(target)
        backup_file(path)
        os.replace(temporary, path)
    finally:
        original.close()
        temporary.unlink(missing_ok=True)


def save_snapshot(snapshot: CourseSnapshot, path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    """Persist complete metadata scan; return changes after initial baseline."""
    code = snapshot.course.course_code
    now = _now()
    changes: list[dict[str, object]] = []
    with connect(path) as db:
        old_course = db.execute("SELECT semester FROM courses WHERE code=?", (code,)).fetchone()
        changed_term = old_course is not None and old_course["semester"] != snapshot.course.semester
        if changed_term:
            db.execute(
                "UPDATE section_scans SET last_successful_at=NULL,last_successful_scan_id=NULL,last_attempt_scan_id=NULL,scope=NULL WHERE course_code=?",
                (code,),
            )
        initial = (
            db.execute(
                "SELECT 1 FROM scan_history WHERE course_code=? AND status='success' LIMIT 1",
                (code,),
            ).fetchone()
            is None
            or changed_term
        )
        previous_id = db.execute(
            "SELECT MAX(id) FROM scan_history WHERE course_code=? AND status='success'", (code,)
        ).fetchone()[0]
        prior = {}
        for table in ("files", "resources", "exams", "calendar_events"):
            prior[table] = (
                [
                    dict(row)
                    for row in db.execute(
                        f"""SELECT t.* FROM {table} t WHERE t.course_code=? AND
                        (t.key IN (SELECT m.item_key FROM section_members m JOIN section_scans s ON s.course_code=m.course_code AND s.section=m.section
                                   AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id WHERE m.course_code=t.course_code AND m.section='{table}')
                         OR (NOT EXISTS(SELECT 1 FROM section_scans s WHERE s.course_code=t.course_code AND s.section='{table}') AND t.last_seen_scan_id=?))""",
                        (code, previous_id),
                    )
                ]
                if not initial
                else []
            )
        active = {table: set() for table in prior}
        active["announcements"] = set()
        scan_id = db.execute(
            "INSERT INTO scan_history (course_code,scanned_at,status) VALUES (?,?,'success')",
            (code, now),
        ).lastrowid
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
            resource_key = _key(code, snapshot.course.semester, resource.url)
            # Reuse legacy keys within the same term to avoid an artificial migration delta.
            legacy = _key(code, resource.url)
            resource_key = _current_key(
                db, "resources", resource_key, legacy, None if changed_term else previous_id
            )
            active["resources"].add(resource_key)
            if (
                resource.detail_error
                and db.execute("SELECT 1 FROM resources WHERE key=?", (resource_key,)).fetchone()
            ):
                continue
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
            db.execute(
                "UPDATE resources SET last_seen_scan_id=? WHERE key=?", (scan_id, resource_key)
            )
            for remote in resource.files:
                file_key = _key(code, snapshot.course.semester, resource.url, remote.name)
                legacy_file = _key(code, resource.url, remote.name)
                file_key = _current_key(
                    db, "files", file_key, legacy_file, None if changed_term else previous_id
                )
                active["files"].add(file_key)
                if file_key in seen_files:
                    raise ValueError(f"DUPLICATE_REMOTE_FILENAME: {remote.name}")
                seen_files.add(file_key)
                old = db.execute("SELECT * FROM files WHERE key=?", (file_key,)).fetchone()
                if old is None:
                    db.execute(
                        """INSERT INTO files
                           (key,resource_key,course_code,name,size,created_at,remote_id,
                            download_url,revision,first_seen_at,last_seen_at,last_seen_scan_id)
                           VALUES (?,?,?,?,?,?,?,?,1,?,?,?)""",
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
                            scan_id,
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
                           revision=revision+?,last_seen_at=?,last_seen_scan_id=? WHERE key=?""",
                        (
                            remote.name,
                            remote.size,
                            remote.created_at,
                            remote.remote_id,
                            remote.download_url,
                            int(updated),
                            now,
                            scan_id,
                            file_key,
                        ),
                    )
        for announcement in snapshot.announcements:
            key = _announcement_key(db, announcement.url)
            active["announcements"].add(key)
            if (
                announcement.detail_error
                and db.execute("SELECT 1 FROM announcements WHERE key=?", (key,)).fetchone()
            ):
                continue
            old = db.execute(
                "SELECT title,posted_at,content FROM announcements WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(_announcement_change("NEW", code, announcement))
            elif old is not None and _announcement_changed(old, announcement):
                changes.append(_announcement_change("UPDATED", code, announcement))
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
            key = (
                _key(code, snapshot.course.semester, event.remote_id)
                if event.remote_id
                else _key(code, snapshot.course.semester, event.date, event.title)
            )
            legacy = _key(code, event.date, event.title)
            if not event.remote_id:
                key = _current_key(
                    db, "calendar_events", key, legacy, None if changed_term else previous_id
                )
            if key in active["calendar_events"]:
                raise ValueError("DUPLICATE_CALENDAR_ID: preserve prior state; inspect source")
            active["calendar_events"].add(key)
            old = db.execute(
                "SELECT date,title,time,location FROM calendar_events WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(
                    {"status": "NEW", "type": "calendar", "course": code, "name": event.title}
                )
            elif old is not None and (old["date"], old["title"], old["time"], old["location"]) != (
                event.date,
                event.title,
                event.time,
                event.location,
            ):
                changes.append(
                    {"status": "UPDATED", "type": "calendar", "course": code, "name": event.title}
                )
            db.execute(
                """INSERT INTO calendar_events
                   (key,course_code,date,title,time,location,first_seen_at,last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                   date=excluded.date,title=excluded.title,time=excluded.time,location=excluded.location,last_seen_at=excluded.last_seen_at""",
                (key, code, event.date, event.title, event.time, event.location, now, now),
            )
            db.execute("UPDATE calendar_events SET last_seen_scan_id=? WHERE key=?", (scan_id, key))
            db.execute(
                "UPDATE calendar_events SET remote_id=?,description=?,source_url=?,event_type=?,end_date=? WHERE key=?",
                (
                    event.remote_id,
                    event.description,
                    event.source_url,
                    event.event_type,
                    event.end_date,
                    key,
                ),
            )
        for exam in snapshot.exams:
            exam_json = json.dumps(exam, sort_keys=True, ensure_ascii=False)
            key = _key(
                code, snapshot.course.semester, str(exam.get("id", exam.get("title", exam_json)))
            )
            legacy = _key(code, str(exam.get("id", exam.get("title", exam_json))))
            key = _current_key(db, "exams", key, legacy, None if changed_term else previous_id)
            active["exams"].add(key)
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
            db.execute("UPDATE exams SET last_seen_scan_id=? WHERE key=?", (scan_id, key))
        for table, rows in prior.items():
            # Calendar views cover one displayed month, not all historical events.
            if table == "calendar_events" or _section_error(snapshot, table):
                continue
            for old in rows:
                if old["key"] not in active[table]:
                    name = (
                        old.get("name")
                        or old.get("title")
                        or json.loads(old["details_json"]).get("title", "Exam")
                    )
                    changes.append(
                        {
                            "status": "REMOVED",
                            "type": {"files": "file", "resources": "resource", "exams": "exam"}[
                                table
                            ],
                            "course": code,
                            "name": name,
                        }
                    )
        if not _section_error(snapshot, "announcements"):
            changes.extend(_removed_members(db, code, "announcements", active["announcements"]))
        if not snapshot.warnings and snapshot.calendar_scope.startswith(
            "Embedded LMS calendar JSON"
        ):
            old_scope = db.execute(
                "SELECT scope FROM section_scans WHERE course_code=? AND section='calendar_events'",
                (code,),
            ).fetchone()
            if old_scope and str(old_scope["scope"]).startswith("Embedded LMS calendar JSON"):
                changes.extend(
                    _removed_members(db, code, "calendar_events", active["calendar_events"])
                )
        for section in ("assignments", "live_lessons", "study_links"):
            items = (
                [asdict(item) for item in snapshot.assignments]
                if section == "assignments"
                else getattr(snapshot, section)
            )
            active[section] = _save_academic_items(
                db,
                code,
                snapshot.course.semester,
                section,
                items,
                scan_id,
                now,
                changes,
                bool(_section_error(snapshot, section)),
            )
        db.executemany(
            "INSERT INTO scan_changes (scan_id,course_code,status,type,name,remote_id,source_url) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    scan_id,
                    code,
                    item["status"],
                    item["type"],
                    item["name"],
                    item.get("remote_id"),
                    item.get("source_url"),
                )
                for item in changes
            ],
        )
        for section, keys in active.items():
            error = _section_error(snapshot, section) or (
                "; ".join(snapshot.warnings)
                if section == "calendar_events" and snapshot.warnings
                else None
            )
            _save_section(
                db,
                code,
                section,
                scan_id,
                now,
                keys,
                error,
                snapshot.calendar_scope if section == "calendar_events" else "Current course page",
            )
    return changes


def _section_error(snapshot, section):
    return (
        "; ".join(
            value for key, value in snapshot.section_errors.items() if key.split(":")[0] == section
        )
        or None
    )


def _save_academic_items(db, code, term, section, items, scan_id, now, changes, partial=False):
    previous = db.execute(
        "SELECT COALESCE(last_attempt_scan_id,last_successful_scan_id) FROM section_scans WHERE course_code=? AND section=?",
        (code, section),
    ).fetchone()
    keys = set()
    for item in items:
        identity = item.get("remote_id") or item.get("url") or item.get("title")
        if section == "live_lessons":
            identity = json.dumps(
                [item.get("url"), item.get("links") or item.get("title")], sort_keys=True
            )
        if not identity:
            raise ValueError("ACADEMIC_IDENTITY_MISSING")
        key = _key(code, term, section, str(identity))
        if key in keys:
            raise ValueError("DUPLICATE_ACADEMIC_IDENTITY")
        keys.add(key)
        old = db.execute("SELECT details_json FROM academic_items WHERE key=?", (key,)).fetchone()
        # Keep last verified detail on transient failure, with the current failure attached.
        if old and item.get("detail_error"):
            item = {**json.loads(old["details_json"]), "detail_error": item["detail_error"]}
        encoded = json.dumps(item, sort_keys=True, ensure_ascii=False)
        before = json.loads(old["details_json"]) if old else None
        stable = lambda value: {
            k: v for k, v in value.items() if k not in {"checked_at", "detail_error"}
        }
        if (
            previous
            and previous[0]
            and not item.get("detail_error")
            and (before is None or stable(before) != stable(item))
        ):
            changes.append(
                {
                    "status": "UPDATED" if old else "NEW",
                    "type": section,
                    "course": code,
                    "name": item.get("title", section),
                    "remote_id": str(identity),
                    "source_url": item.get("url", ""),
                }
            )
        db.execute(
            """INSERT INTO academic_items VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
            title=excluded.title,details_json=excluded.details_json,last_seen_at=excluded.last_seen_at,last_seen_scan_id=excluded.last_seen_scan_id""",
            (key, code, section, item.get("title", section), encoded, now, now, scan_id),
        )
    if previous and previous[0] and not partial:
        for old in db.execute(
            """SELECT a.* FROM academic_items a JOIN section_members m ON m.item_key=a.key
                               WHERE m.course_code=? AND m.section=? AND m.scan_id=?""",
            (code, section, previous[0]),
        ):
            if old["key"] not in keys:
                item = json.loads(old["details_json"])
                changes.append(
                    {
                        "status": "REMOVED",
                        "type": section,
                        "course": code,
                        "name": old["title"],
                        "remote_id": item.get("remote_id", ""),
                        "source_url": item.get("url", ""),
                    }
                )
    return keys


def _removed_members(db, code, section, keys):
    if section not in {"announcements", "calendar_events"}:
        raise ValueError("INVALID_SECTION")
    rows = db.execute(
        f"""SELECT t.key,t.title,t.course_code,s.scope FROM {section} t
        JOIN section_members m ON m.item_key=t.key JOIN section_scans s ON s.course_code=m.course_code AND s.section=m.section AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id
        WHERE m.course_code=? AND m.section=?""",
        (code, section),
    ).fetchall()
    return [
        {
            "status": "REMOVED",
            "type": "announcement" if section == "announcements" else "calendar",
            "course": row["course_code"],
            "name": row["title"],
            "scope": row["scope"],
            "meaning": "No longer visible in this successfully scanned scope; cancellation not inferred",
        }
        for row in rows
        if row["key"] not in keys
    ]


def _save_section(
    db, code, section, scan_id, now, keys, error=None, scope="Current displayed scope"
):
    prior_keys = (
        {
            row[0]
            for row in db.execute(
                """SELECT m.item_key FROM section_members m JOIN section_scans s
        ON s.course_code=m.course_code AND s.section=m.section AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id
        WHERE m.course_code=? AND m.section=?""",
                (code, section),
            )
        }
        if error
        else set()
    )
    db.execute(
        """INSERT INTO section_scans (course_code,section,attempted_at,last_successful_at,last_successful_scan_id,error,scope,last_attempt_scan_id) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(course_code,section) DO UPDATE SET attempted_at=excluded.attempted_at,
        last_successful_at=CASE WHEN excluded.error IS NULL THEN excluded.last_successful_at ELSE section_scans.last_successful_at END,
        last_successful_scan_id=CASE WHEN excluded.error IS NULL THEN excluded.last_successful_scan_id ELSE section_scans.last_successful_scan_id END,
        error=excluded.error,scope=CASE WHEN excluded.error IS NULL THEN excluded.scope ELSE section_scans.scope END,
        last_attempt_scan_id=excluded.last_attempt_scan_id""",
        (
            code,
            section,
            now,
            now if error is None else None,
            scan_id if error is None else None,
            error,
            scope,
            scan_id,
        ),
    )
    members = set(keys)
    if error:
        members.update(prior_keys)
    db.executemany(
        "INSERT OR IGNORE INTO section_members VALUES (?,?,?,?)",
        [(code, section, scan_id, key) for key in members],
    )


def latest_files(path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with connect(path, readonly=True) as db:
        rows = db.execute(
            """SELECT f.course_code,f.name,f.size,f.created_at,f.remote_id,f.download_url,
                      f.revision,f.last_seen_at AS scanned_at,r.title AS resource_title,r.url AS resource_url,
                      c.semester
               FROM files f JOIN resources r ON f.resource_key=r.key LEFT JOIN courses c ON c.code=f.course_code
               WHERE f.last_seen_scan_id = (
                 SELECT h.id FROM scan_history h
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


def save_global_section(section: str, items: list[dict], errors=None, path: Path = DEFAULT_DB):
    if section not in ACADEMIC_SECTIONS:
        raise ValueError("INVALID_SECTION")
    now, changes = _now(), []
    with connect(path) as db:
        scan_id = db.execute(
            "INSERT INTO scan_history (course_code,scanned_at,status) VALUES ('GLOBAL',?,'success')",
            (now,),
        ).lastrowid
        keys = _save_academic_items(
            db, "GLOBAL", "global", section, items, scan_id, now, changes, bool(errors)
        )
        _save_section(
            db,
            "GLOBAL",
            section,
            scan_id,
            now,
            keys,
            "; ".join(errors.values()) if errors else None,
            "Complete paginated list"
            if section == "notifications"
            else "Followed catalogue courses only",
        )
        db.executemany(
            "INSERT INTO scan_changes (scan_id,course_code,status,type,name,remote_id,source_url) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    scan_id,
                    "GLOBAL",
                    item["status"],
                    item["type"],
                    item["name"],
                    item.get("remote_id"),
                    item.get("source_url"),
                )
                for item in changes
            ],
        )
    return changes


def get_new_items(
    path: Path = DEFAULT_DB,
    *,
    since_scan_id: int | None = None,
    after_change_id: int = 0,
    limit: int = 100,
) -> list[dict]:
    """Persistent unseen changes. Reading and rescanning never acknowledge them."""
    if (
        (since_scan_id is not None and (type(since_scan_id) is not int or since_scan_id < 0))
        or type(after_change_id) is not int
        or after_change_id < 0
        or type(limit) is not int
        or not 1 <= limit <= 500
    ):
        raise ValueError("CHANGE_CURSOR_INVALID")
    if not path.exists():
        return []
    with connect(path, readonly=True) as db:
        rows = db.execute(
            """SELECT c.rowid AS change_id,c.scan_id,h.scanned_at,c.course_code,c.status,c.type,c.name,c.remote_id,c.source_url
               FROM scan_changes c JOIN scan_history h ON h.id=c.scan_id
               WHERE c.rowid>? AND (? IS NULL OR c.scan_id>?)
               AND (? IS NOT NULL OR c.rowid>COALESCE((SELECT through_change_id FROM change_acknowledgements WHERE consumer='default'),0))
               ORDER BY c.rowid LIMIT ?""",
            (after_change_id, since_scan_id, since_scan_id, since_scan_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def acknowledge_changes(through_change_id: int, path: Path = DEFAULT_DB) -> dict:
    if type(through_change_id) is not int or through_change_id < 1:
        raise ValueError("CHANGE_CURSOR_INVALID")
    with connect(path) as db:
        if (
            through_change_id
            > db.execute("SELECT COALESCE(MAX(rowid),0) FROM scan_changes").fetchone()[0]
        ):
            raise ValueError("CHANGE_CURSOR_UNKNOWN")
        db.execute(
            """INSERT INTO change_acknowledgements VALUES ('default',?) ON CONFLICT(consumer)
                      DO UPDATE SET through_change_id=MAX(through_change_id,excluded.through_change_id)""",
            (through_change_id,),
        )
        return {
            "acknowledged_through_change_id": db.execute(
                "SELECT through_change_id FROM change_acknowledgements WHERE consumer='default'"
            ).fetchone()[0],
            "scope": "Local LMS changes only; portal notifications unchanged",
        }


def get_rows(
    table: str, course_code: str | None = None, path: Path = DEFAULT_DB
) -> list[dict[str, object]]:
    allowed = {
        "courses",
        "resources",
        "files",
        "announcements",
        "exams",
        "calendar_events",
    } | ACADEMIC_SECTIONS
    if table not in allowed:
        raise ValueError("INVALID_TABLE")
    if not path.exists():
        return []
    with connect(path, readonly=True) as db:
        if table in ACADEMIC_SECTIONS:
            rows = db.execute(
                """SELECT DISTINCT a.* FROM academic_items a JOIN section_members m ON m.item_key=a.key
                JOIN section_scans s ON s.course_code=m.course_code AND s.section=m.section
                AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id
                WHERE a.section=? AND m.section=? AND (? IS NULL OR a.course_code=?) ORDER BY a.rowid""",
                (table, table, course_code, course_code),
            ).fetchall()
            return [
                {
                    **json.loads(row["details_json"]),
                    "key": row["key"],
                    "course_code": json.loads(row["details_json"]).get(
                        "course_code", row["course_code"]
                    ),
                    "scanned_at": row["last_seen_at"],
                    "scan_id": row["last_seen_scan_id"],
                }
                for row in rows
            ]
        if table in {"resources", "files", "exams", "calendar_events"}:
            condition = "AND t.course_code=?" if course_code else ""
            fields = "t.*"
            joins = ""
            if table == "files":
                fields += ", t.last_seen_at AS scanned_at,r.title AS resource_title,r.url AS resource_url,c.semester"
                joins = "JOIN resources r ON t.resource_key=r.key LEFT JOIN courses c ON c.code=t.course_code"
            rows = db.execute(
                f"""SELECT {fields} FROM {table} t {joins} WHERE (t.key IN (
                SELECT m.item_key FROM section_members m JOIN section_scans s
                ON s.course_code=m.course_code AND s.section=m.section
                AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id
                WHERE m.course_code=t.course_code AND m.section='{table}')
                OR (NOT EXISTS(SELECT 1 FROM section_scans s WHERE s.course_code=t.course_code AND s.section='{table}') AND t.last_seen_scan_id = (
                SELECT COALESCE((SELECT s.last_successful_scan_id FROM section_scans s WHERE s.course_code=t.course_code AND s.section='{table}'),
                    MAX(h.id)) FROM scan_history h WHERE h.course_code=t.course_code AND h.status='success'
            ))) {condition} ORDER BY t.rowid""",
                (course_code,) if course_code else (),
            ).fetchall()
            return [dict(row) for row in rows]
        if table == "announcements":
            rows = db.execute(
                """SELECT DISTINCT a.* FROM announcements a JOIN section_members m ON m.item_key=a.key
                JOIN section_scans s ON s.course_code=m.course_code AND s.section=m.section AND COALESCE(s.last_attempt_scan_id,s.last_successful_scan_id)=m.scan_id
                WHERE m.section='announcements' AND (? IS NULL OR a.course_code=?) ORDER BY a.rowid""",
                (course_code, course_code),
            ).fetchall()
            return [dict(row) for row in rows]
        if course_code:
            column = "code" if table == "courses" else "course_code"
            rows = db.execute(
                f"SELECT * FROM {table} WHERE {column}=? ORDER BY rowid", (course_code,)
            ).fetchall()
        else:
            rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        return [dict(row) for row in rows]


def save_dashboard_announcements(
    entries: list[tuple[str, Announcement]], path: Path = DEFAULT_DB, *, errors: dict | None = None
) -> list[dict[str, object]]:
    now = _now()
    changes: list[dict[str, object]] = []
    seen = set()
    with connect(path) as db:
        initial = (
            db.execute(
                "SELECT 1 FROM scan_history WHERE course_code='GLOBAL' AND status='success' LIMIT 1"
            ).fetchone()
            is None
        )
        for course_code, announcement in entries:
            key = _announcement_key(db, announcement.url)
            seen.add(key)
            if (
                announcement.detail_error
                and db.execute("SELECT 1 FROM announcements WHERE key=?", (key,)).fetchone()
            ):
                continue
            old = db.execute(
                "SELECT title,posted_at,content FROM announcements WHERE key=?", (key,)
            ).fetchone()
            if old is None and not initial:
                changes.append(_announcement_change("NEW", course_code, announcement))
            elif old is not None and _announcement_changed(old, announcement):
                changes.append(_announcement_change("UPDATED", course_code, announcement))
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
        if not errors:
            changes.extend(_removed_members(db, "GLOBAL", "announcements", seen))
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
        _save_section(
            db,
            "GLOBAL",
            "announcements",
            cursor.lastrowid,
            now,
            seen,
            error="; ".join(errors.values()) if errors else None,
            scope="All Announcements; paginated list and detail pages",
        )
    return changes


def stored_section(
    table: str,
    course_code: str | None = None,
    path: Path = DEFAULT_DB,
    *,
    since_scan_id: int | None = None,
    after_change_id: int = 0,
    limit: int = 100,
    offset: int | None = None,
) -> dict:
    """Return cached data together with section-level validity; never initialize storage."""
    items = (
        get_new_items(
            path, since_scan_id=since_scan_id, after_change_id=after_change_id, limit=limit
        )
        if table == "changes"
        else get_rows(table, course_code, path)
    )
    if offset is not None and (
        type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500
    ):
        raise ValueError("PAGE_ARGUMENT_INVALID")
    total_items = len(items)
    statuses = []
    if path.exists():
        with connect(path, readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM section_scans WHERE (?='changes' OR section=?) AND (? IS NULL OR course_code=? OR (section='announcements' AND course_code='GLOBAL'))",
                (table, table, course_code, course_code),
            ).fetchall()
            for row in rows:
                status = dict(row)
                course = db.execute(
                    "SELECT url FROM courses WHERE code=?", (row["course_code"],)
                ).fetchone()
                status["source_url"] = (course["url"] if course else None) or LMS_URL
                status["scanned_at"] = row["last_successful_at"]
                failure = db.execute(
                    "SELECT error FROM scan_history WHERE status='failed' AND course_code IN (?, 'GLOBAL') AND scanned_at>? ORDER BY id DESC LIMIT 1",
                    (row["course_code"], row["attempted_at"]),
                ).fetchone()
                error = failure["error"] if failure else row["error"]
                status.update(
                    source="LMS",
                    freshness="STALE"
                    if error and row["last_successful_at"]
                    else "UNKNOWN"
                    if not row["last_successful_at"]
                    else "FRESH_AT_SCAN",
                    completeness="INCOMPLETE"
                    if error or not row["last_successful_at"]
                    else "COMPLETE_IN_SCOPE",
                    error=error,
                    availability="Scan failed"
                    if error
                    else "Unknown"
                    if not row["last_successful_at"]
                    else "Data available"
                    if any(item.get("course_code") == row["course_code"] for item in items)
                    else "Not announced yet",
                    data_age_seconds=max(
                        0,
                        (
                            datetime.now(UTC) - datetime.fromisoformat(row["last_successful_at"])
                        ).total_seconds(),
                    )
                    if row["last_successful_at"]
                    else None,
                )
                statuses.append(status)
    return {
        "source": "LMS",
        "section": table,
        "items": items[offset : offset + limit]
        if offset is not None and table != "changes"
        else items,
        "sections": statuses,
        "completeness": "COMPLETE_IN_SCANNED_SCOPES"
        if statuses and all(s["completeness"] == "COMPLETE_IN_SCOPE" for s in statuses)
        else "PARTIAL",
        "errors": [s["error"] for s in statuses if s["error"]]
        if statuses
        else ["NOT_SCANNED: run a fresh scan; preserved history is not current verification"],
        **(
            {
                "next_after_change_id": items[-1]["change_id"] if items else after_change_id,
                "has_more": len(items) == limit,
            }
            if table == "changes"
            else {}
        ),
        **(
            {
                "total_items": total_items,
                "has_more": offset + limit < total_items,
                "next_offset": offset + limit if offset + limit < total_items else None,
            }
            if offset is not None and table != "changes"
            else {}
        ),
    }
