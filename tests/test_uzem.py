"""Legacy UZEM read-only and update comparison boundaries."""

from app.uzem import portal, updates


def test_safe_url_rejects_external_and_action_links() -> None:
    assert portal._safe_url("https://uzem.altinbas.edu.tr/course/view.php?id=123")
    assert portal._safe_url("https://other.example/course/view.php?id=123") is None
    assert portal._safe_url("http://uzem.altinbas.edu.tr/course/view.php?id=123") is None
    assert portal._safe_url("https://uzem.altinbas.edu.tr/action.php?sesskey=secret") is None


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
    monkeypatch.setattr(updates.portal, "scan_all", lambda: snapshot)
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
    monkeypatch.setattr(updates.portal, "scan_all", lambda: snapshot)
    state_path = tmp_path / "uzem.json"
    updates.scan_updates(state_path)
    snapshot["scan_errors"] = {"notifications": "unavailable"}
    failed = updates.scan_updates(state_path)
    assert "notifications" not in failed["scanned_sections"]
