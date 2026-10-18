import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.config import Config
from app.drive.comparator import compare_file
from app.drive.sync import (
    install_download,
    validate_content,
    validate_destination,
    validate_download_url,
)
from app.storage import database, state
from tests.test_file_regressions import metadata


def test_same_size_remote_identity_change_and_local_tampering(tmp_path, monkeypatch):
    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    row = metadata()
    incoming = tmp_path / "incoming"
    incoming.write_bytes(b"x" * 1024)
    installed = install_download(incoming, compare_file(row, config), row["size"])
    assert compare_file(row, config).status == "PRESENT"
    assert compare_file({**row, "remote_id": "43"}, config).status == "UPDATED"
    assert compare_file({**row, "created_at": "2026-10-16"}, config).status == "UPDATED"
    installed.write_bytes(b"z" * 1024)
    assert compare_file(row, config).status == "UPDATED"
    installed.write_bytes(b"z" * 500)
    monkeypatch.setattr(
        "app.drive.comparator.file_hash",
        Mock(side_effect=AssertionError("Size mismatch should not hash file")),
    )
    assert compare_file(row, config).status == "UPDATED"


def test_interruption_between_install_and_receipt_reuses_bytes(tmp_path, monkeypatch):
    from app.drive import sync

    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    row = metadata()
    incoming = tmp_path / "incoming"
    incoming.write_bytes(b"x" * 1024)
    original = sync.record_install
    monkeypatch.setattr(sync, "record_install", Mock(side_effect=OSError("Simulated interruption")))
    with pytest.raises(OSError):
        install_download(incoming, compare_file(row, config), row["size"])
    monkeypatch.setattr(sync, "record_install", original)
    install_download(incoming, compare_file(row, config), row["size"])
    assert len(list((tmp_path / "University").rglob("*.pdf"))) == 1
    assert compare_file(row, config).status == "PRESENT"


def test_term_receipt_is_not_reused(tmp_path):
    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    row = metadata()
    incoming = tmp_path / "incoming"
    incoming.write_bytes(b"x" * 1024)
    install_download(incoming, compare_file(row, config), row["size"])
    assert compare_file(row, replace(config, term="Fall 2027/2028")).status != "PRESENT"


@pytest.mark.parametrize(
    "url",
    [
        "http://uzem.altinbas.edu.tr/pluginfile.php/1/a.pdf",
        "https://uzem.altinbas.edu.tr.evil.test/pluginfile.php/1/a.pdf",
        "https://uzem.altinbas.edu.tr:444/pluginfile.php/1/a.pdf",
        "https://user:pass@uzem.altinbas.edu.tr/pluginfile.php/1/a.pdf",
        "https://uzem.altinbas.edu.tr/login/index.php",
        "https://uzem.altinbas.edu.tr/mod/resource/view.php?id=1&sesskey=hidden",
    ],
)
def test_reject_unsafe_download_destinations(url):
    with pytest.raises(ValueError):
        validate_download_url(url, "UZEM")


def test_reject_html_and_disguised_file_types(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.write_bytes(b"<html>Sign in</html>")
    with pytest.raises(ValueError, match="HTML_REJECTED"):
        validate_content(incoming, "a.pdf", "text/html")
    incoming.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="SIGNATURE_INVALID"):
        validate_content(incoming, "a.pdf", "application/pdf")
    with pytest.raises(ValueError, match="TYPE_REJECTED"):
        validate_content(incoming, "a.exe", "application/octet-stream")


def test_destination_rejects_escape_and_directory_junction(tmp_path):
    root = tmp_path / "Drive"
    university = root / "University"
    university.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        validate_destination(outside / "a.pdf", root)
    link = university / "SWE431"
    if os.name == "nt":
        # Native junction creation requires no symlink privilege. No shell deletion is used.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=False
        )
        assert result.returncode == 0
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError):
            validate_destination(link / "a.pdf", root)
    finally:
        link.rmdir() if os.name == "nt" else link.unlink()


def test_state_backup_recovery_retention_and_failed_replace(tmp_path, monkeypatch):
    path = tmp_path / "updates.json"
    for number in range(8):
        state.save_state(path, {"version": 1, "sections": {"n": number}})
    backups = list((tmp_path / "backups").glob("*.bak"))
    assert len(backups) == 5
    original = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(state.os, "replace", Mock(side_effect=OSError("Interrupted replace")))
        with pytest.raises(OSError):
            state.save_state(path, {"version": 1, "sections": {}})
    assert path.read_bytes() == original
    backups = list((tmp_path / "backups").glob("*.bak"))
    backup = max(backups, key=lambda p: p.stat().st_mtime_ns)
    path.write_text("corrupted")
    state.recover_state(path, backup)
    assert isinstance(state.load_state(path)["sections"], dict)


def test_process_lock_released_after_interruption(tmp_path):
    lock = tmp_path / "process.lock"
    code = "from pathlib import Path; from app.storage.state import operation_lock; import sys,time;\nwith operation_lock(Path(sys.argv[1])):\n print('LOCKED',flush=True); time.sleep(30)"
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(lock)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="SCAN_BUSY"), state.operation_lock(lock):
            pytest.fail("Overlapping process acquired lock")
    finally:
        child.terminate()
        child.wait(timeout=5)
    for attempt in range(100):
        try:
            with state.operation_lock(lock):
                break
        except RuntimeError:
            if attempt == 99:
                raise
            time.sleep(0.02)


def test_migration_backed_up_before_schema_change(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE resources (key TEXT PRIMARY KEY, title TEXT)")
    with database.connect(path):
        pass
    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert "last_seen_scan_id" not in {
            row[1] for row in db.execute("PRAGMA table_info(resources)")
        }


def test_database_recovery_preserves_corrupt_original(tmp_path):
    path = tmp_path / "state.sqlite"
    backups = tmp_path / "backups"
    backups.mkdir()
    backup = backups / "valid.sqlite"
    with sqlite3.connect(backup) as db:
        db.execute("CREATE TABLE evidence (value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('preserved')")
    path.write_bytes(b"corrupt original")
    database.recover_database(path, backup)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM evidence").fetchone()[0] == "preserved"
    assert next(backups.glob("state.sqlite.*.bak")).read_bytes() == b"corrupt original"


def test_invalid_database_backup_does_not_replace_original(tmp_path):
    path = tmp_path / "state.sqlite"
    backups = tmp_path / "backups"
    backups.mkdir()
    backup = backups / "bad.sqlite"
    backup.write_bytes(b"invalid backup")
    path.write_bytes(b"keep original")
    with pytest.raises(sqlite3.DatabaseError):
        database.recover_database(path, backup)
    assert path.read_bytes() == b"keep original"


def test_sqlite_backup_retention_and_future_schema_preservation(tmp_path):
    path = tmp_path / "state.sqlite"
    for _ in range(8):
        with database.connect(path):
            pass
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=0")
    assert len(list((tmp_path / "backups").glob("*.migration-*.sqlite"))) == 5
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="STATE_VERSION_UNSUPPORTED"), database.connect(path):
        pass
    assert path.read_bytes() == original


def test_health_cli_fails_for_blocked_session(monkeypatch, capsys):
    from app import cli
    from app.services import health

    result = {"drive": {"mounted_available": True}, "sessions": {"UZEM": {"authenticated": False}}}
    monkeypatch.setattr(health, "university_health", lambda: result)
    assert cli.main(["university-health"]) == 1
    result["sessions"]["UZEM"]["authenticated"] = True
    assert cli.main(["university-health"]) == 0
    assert "authenticated" in capsys.readouterr().out
