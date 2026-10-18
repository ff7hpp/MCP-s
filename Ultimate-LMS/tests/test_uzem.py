"""Legacy UZEM read-only and update comparison boundaries."""

from unittest.mock import Mock

import pytest

from app.config import Config
from app.uzem import portal, updates
from app.uzem import sync as uzem_sync


def test_safe_url_rejects_external_and_action_links() -> None:
    assert portal._safe_url("https://uzem.altinbas.edu.tr/course/view.php?id=123")
    assert portal._safe_url("https://other.example/course/view.php?id=123") is None
    assert portal._safe_url("http://uzem.altinbas.edu.tr/course/view.php?id=123") is None
    assert portal._safe_url("https://uzem.altinbas.edu.tr/action.php?sesskey=secret") is None
    assert portal._safe_url(
        "https://uzem.altinbas.edu.tr/mod/forum/discuss.php?d=1", "/mod/forum/discuss.php"
    )
    assert (
        portal._safe_url(
            "https://uzem.altinbas.edu.tr/mod/forum/discuss.php?d=1&ses%73key=private",
            "/mod/forum/discuss.php",
        )
        is None
    )


def test_first_scan_is_baseline_and_later_activity_is_new(tmp_path, monkeypatch) -> None:
    snapshot = {
        "courses": [
            {"id": 1, "name": "Course", "url": "https://uzem.altinbas.edu.tr/course/view.php?id=1"}
        ],
        "course_details": [
            {"course": {"id": 1}, "sections": [{"title": "General", "activities": []}]}
        ],
        "announcements": [],
        "notifications": [],
        "calendar": [],
        "grades": [],
        "scan_errors": {},
    }
    monkeypatch.setattr(updates.portal, "scan_all", lambda **kwargs: snapshot)
    state_path = tmp_path / "uzem.json"
    first = updates.scan_updates(state_path)
    assert first["new_count"] == 0
    assert "activities" in first["baseline_sections"]
    snapshot["course_details"][0]["sections"][0]["activities"].append(
        {
            "id": 4,
            "type": "resource",
            "title": "New file",
            "url": "https://uzem.altinbas.edu.tr/mod/resource/view.php?id=4",
        }
    )
    second = updates.scan_updates(state_path)
    assert second["new_count"] == 1
    assert second["changes"][0]["section"] == "activities"
    assert updates.scan_updates(state_path)["changes"] == []


def test_failed_section_keeps_previous_baseline(tmp_path, monkeypatch) -> None:
    snapshot = {
        "courses": [],
        "course_details": [],
        "announcements": [],
        "notifications": [],
        "calendar": [],
        "grades": [],
        "scan_errors": {},
    }
    monkeypatch.setattr(updates.portal, "scan_all", lambda **kwargs: snapshot)
    state_path = tmp_path / "uzem.json"
    updates.scan_updates(state_path)
    snapshot["scan_errors"] = {"notifications": "unavailable"}
    failed = updates.scan_updates(state_path)
    assert "notifications" not in failed["scanned_sections"]


def test_sync_rejects_failed_course_scan(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        uzem_sync, "load_config", lambda: Config(term="Fall 2026/2027", drive_root=tmp_path)
    )
    monkeypatch.setattr(
        uzem_sync.portal,
        "scan_all",
        lambda **kwargs: {
            "courses": [{"id": 1, "name": "SWE431 Testing"}],
            "files": [],
            "scan_errors": {"course:1": "course page failed"},
        },
    )
    with pytest.raises(RuntimeError, match="UZEM_SCAN_INCOMPLETE"):
        uzem_sync.prepare_sync("SWE431")


def test_sync_rejects_unknown_course(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        uzem_sync, "load_config", lambda: Config(term="Fall 2026/2027", drive_root=tmp_path)
    )
    monkeypatch.setattr(
        uzem_sync.portal,
        "scan_all",
        lambda **kwargs: {"courses": [], "files": [], "scan_errors": {}},
    )
    with pytest.raises(RuntimeError, match="UZEM_COURSE_NOT_FOUND"):
        uzem_sync.prepare_sync("SWE431")


def test_scoped_sync_ignores_unrelated_course_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        uzem_sync, "load_config", lambda: Config(term="Fall 2026/2027", drive_root=tmp_path)
    )
    monkeypatch.setattr(
        uzem_sync.portal,
        "scan_all",
        lambda **kwargs: {
            "courses": [
                {"id": 1, "name": "SWE431 Testing"},
                {"id": 2, "name": "IE208 Economics"},
            ],
            "files": [],
            "scan_errors": {"course:2": "course page failed"},
        },
    )
    assert uzem_sync.prepare_sync("SWE431") == []


def test_sync_does_not_treat_missing_file_metadata_as_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(
        uzem_sync, "load_config", lambda: Config(term="Fall 2026/2027", drive_root=tmp_path)
    )
    monkeypatch.setattr(
        uzem_sync.portal,
        "scan_all",
        lambda **kwargs: {
            "courses": [],
            "files": [],
            "scan_errors": {"files": "UZEM_FILE_METADATA_UNAVAILABLE"},
        },
    )
    with pytest.raises(RuntimeError, match="UZEM_SCAN_INCOMPLETE"):
        uzem_sync.prepare_sync()


def test_resource_identity_stays_stable_across_file_redirects():
    resource = "https://uzem.altinbas.edu.tr/mod/resource/view.php?id=1"
    file_url = "https://uzem.altinbas.edu.tr/pluginfile.php/42/mod_resource/content/2/lecture.pdf"
    redirect = Mock(status=302, headers={"location": file_url})
    final = Mock(
        status=200,
        url=file_url,
        headers={
            "content-type": "application/pdf",
            "content-length": "100",
            "content-disposition": 'attachment; filename="lecture.pdf"',
            "etag": '"revision-2"',
        },
    )
    page = Mock()
    page.context.request.head.side_effect = [redirect, final]
    row = portal._resource_metadata(
        page, {"name": "MMF401 Safety"}, {"id": 1, "title": "Introduction", "url": resource}
    )
    assert row["resource_url"] == resource
    assert row["download_url"] == file_url
    assert row["etag"] == '"revision-2"'
