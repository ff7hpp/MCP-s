import json
import sqlite3
import zipfile

import pytest

from app.storage.backup import create_backup, restore_to_new_directory


def test_backup_restore_includes_profiles_but_does_not_overwrite_live_state(tmp_path):
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    (root / "config.toml").write_text('term="Fall 2026/2027"')
    (root / "data" / "ewi_updates.json").write_text('{"version":1,"sections":{}}')
    for name in ("daily.json", "auth_retry.json"):
        (root / "data" / name).write_text('{"version":1,"sections":{}}')
    (root / "data" / "daily-reports").mkdir()
    (root / "data" / "daily-reports" / "daily-fixture.md").write_text("Daily fixture")
    (root / "browser-profile").mkdir()
    (root / "browser-profile" / "Preferences").write_text("synthetic profile")
    with sqlite3.connect(root / "data" / "state.sqlite") as db:
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('preserved')")
    archive = create_backup(root, include_profiles=True)
    destination = tmp_path / "restored"
    restore_to_new_directory(archive, destination)
    assert (destination / "browser-profile" / "Preferences").read_text() == "synthetic profile"
    assert (
        destination / "data" / "daily-reports" / "daily-fixture.md"
    ).read_text() == "Daily fixture"
    assert (destination / "data" / "daily.json").is_file()
    assert (destination / "data" / "auth_retry.json").is_file()
    with sqlite3.connect(destination / "data" / "state.sqlite") as db:
        assert db.execute("SELECT value FROM evidence").fetchone()[0] == "preserved"
    with pytest.raises(ValueError, match="RESTORE_DESTINATION_EXISTS"):
        restore_to_new_directory(archive, root)
    assert (root / "config.toml").read_text() == 'term="Fall 2026/2027"'


def test_restore_rejects_traversal_without_writing_outside_staging(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../outside.txt", "unsafe")
        zipped.writestr(
            "manifest.json", json.dumps({"../outside.txt": {"size": 6, "sha256": "bad"}})
        )
    with pytest.raises(ValueError, match="BACKUP_MEMBER_PATH_INVALID"):
        restore_to_new_directory(archive, tmp_path / "restored")
    assert not (tmp_path / "outside.txt").exists()


def test_restore_rejects_changed_content(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("config.toml", "changed")
        zipped.writestr(
            "manifest.json", json.dumps({"config.toml": {"size": 7, "sha256": "incorrect"}})
        )
    with pytest.raises(ValueError, match="BACKUP_CONTENT_MISMATCH"):
        restore_to_new_directory(archive, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
