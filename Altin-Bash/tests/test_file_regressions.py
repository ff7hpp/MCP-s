from pathlib import Path

from app.config import Config
from app.drive.comparator import compare_file, course_target, safe_component
from app.drive.sync import install_download


def metadata():
    return {
        "course_code": "SWE431",
        "semester": "Fall 2026/2027",
        "name": "Lecture.pdf",
        "size": "1024 B",
        "revision": 2,
        "remote_id": "42",
        "created_at": "2026-10-15",
        "resource_title": "Lectures",
        "resource_url": "https://lms.altinbas.edu.tr/resource?CRID=2",
        "download_url": "https://lms.altinbas.edu.tr/file?DownloadFile=42",
    }


def test_updated_download_is_present_on_repeat(tmp_path: Path):
    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    row = metadata()
    source = tmp_path / "incoming"
    source.write_bytes(b"x" * 1024)
    comparison = compare_file(row, config)
    install_download(source, comparison, row["size"])
    assert compare_file(row, config).status == "PRESENT"


def test_prior_term_is_not_present(tmp_path: Path):
    old = tmp_path / "University" / "Fall 2025-2026" / "SWE431" / "Lecture.pdf"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x" * 1024)
    assert (
        compare_file(metadata(), Config(term="Fall 2026/2027", drive_root=tmp_path)).status
        != "PRESENT"
    )


def test_shortened_filename_keeps_extension(tmp_path: Path):
    name = "A" * 140 + ".pdf"
    assert safe_component(name).endswith(".pdf")
    assert (
        course_target(
            Config(term="Fall 2026/2027", drive_root=tmp_path), "SWE431", "Lectures", "", name
        ).suffix
        == ".pdf"
    )


def test_stored_prior_semester_cannot_become_current_present(tmp_path, monkeypatch):
    from dataclasses import replace
    from unittest.mock import Mock

    import pytest

    from app.drive.sync import transfer_file
    from app.lms.models import RemoteFile
    from app.storage.database import latest_files, save_snapshot
    from tests.test_database import snapshot

    old = snapshot([RemoteFile("old.pdf", "10 B", "old", "https://example.test", "1")])
    old = replace(old, course=replace(old.course, semester="Fall 2025/2026"))
    path = tmp_path / "audit.sqlite"
    save_snapshot(old, path)
    row = latest_files(path)[0]
    assert row["semester"] == "Fall 2025/2026"
    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    comparison = compare_file(row, config)
    assert comparison.status == "UNKNOWN"
    assert "SOURCE_TERM_MISMATCH" in comparison.reason
    monkeypatch.setattr("app.config.load_config", lambda: config)
    context = Mock()
    with pytest.raises(RuntimeError, match="SOURCE_TERM_MISMATCH"):
        transfer_file(context, row, comparison, source="LMS")
    context.cookies.assert_not_called()


def test_logical_filename_resolves_verified_revision_and_rejects_tampering(tmp_path, monkeypatch):
    import pytest

    from app.drive import records
    from app.services import documents
    from app.storage.state import load_state, save_state

    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    monkeypatch.setattr(documents, "load_config", lambda: config)
    monkeypatch.setattr(records, "STATE_PATH", tmp_path / "sync_records.json")
    row = {**metadata(), "name": "syllabus.txt", "size": "8 B"}
    source = tmp_path / "incoming"
    source.write_bytes(b"Syllabus")
    installed = install_download(source, compare_file(row, config), row["size"])
    state = load_state(records.STATE_PATH)
    state["sections"]["legacy"] = {
        "path": "old.pdf",
        "revision": "r",
        "sha256": "0" * 64,
        "size": 1,
    }
    save_state(records.STATE_PATH, state)
    assert installed.name != "syllabus.txt"
    assert documents.find_file("SWE431", "syllabus.txt") == installed.resolve()
    installed.write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="LOCAL_SYNC_FILE_UNAVAILABLE"):
        documents.find_file("SWE431", "syllabus.txt")
