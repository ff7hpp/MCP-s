from contextlib import nullcontext

import pytest

from app.ewi import portal
from app.ewi import updates as ewi
from app.services import update
from app.storage.state import load_state


def test_ewi_same_title_body_edit_is_detected_and_failure_preserves_fingerprint(
    monkeypatch, tmp_path
):
    body = {"content": "Original instructions"}
    for name in ("get_notifications", "get_schedule", "get_course_resources", "list_courses"):
        monkeypatch.setattr(portal, name, list)
    monkeypatch.setattr(portal, "read_batch", lambda: nullcontext())
    monkeypatch.setattr(
        portal,
        "get_news",
        lambda: [
            {
                "title": "Homework",
                "date": "18.10.2026",
                "url": "https://ewi.altinbas.edu.tr/web/News/ReadNews?NewsID=1",
            }
        ],
    )
    monkeypatch.setattr(portal, "get_news_detail", lambda _id: {"title": "Homework", **body})
    path = tmp_path / "ewi_updates.json"
    assert ewi.scan_updates(path)["changes"] == []
    body["content"] = "Revised deadline instructions"
    result = ewi.scan_updates(path)
    assert result["updated_count"] == 1
    assert result["changes"][0]["item"]["content"] == body["content"]
    prior = load_state(path)["sections"]["news"]

    def fail(_id):
        raise RuntimeError("NEWS_DETAIL_FAILED")

    monkeypatch.setattr(portal, "get_news_detail", fail)
    result = ewi.scan_updates(path)
    assert "news" in result["scan_errors"]
    assert load_state(path)["sections"]["news"] == prior


def test_selected_lms_skips_unrequested_portals(monkeypatch):
    monkeypatch.setattr(update, "scan_all", list)

    def unexpected(**kwargs):
        pytest.fail("Unrequested portal was accessed")

    monkeypatch.setattr(update, "ewi_updates", unexpected)
    monkeypatch.setattr(update, "uzem_updates", unexpected)
    monkeypatch.setattr(update, "new_alerts", lambda items: [])
    result = update.university_update(sources=["LMS"])
    assert result["source_status"]["UZEM"]["status"] == "Not scanned"
    assert result["source_status"]["LMS"]["duration_ms"] >= 0


@pytest.mark.parametrize("sources", [[], ["LMS", "LMS"], ["OTHER"], "LMS"])
def test_source_selection_rejects_invalid_values(sources):
    with pytest.raises(RuntimeError, match="SOURCE_SELECTION_INVALID"):
        update.university_update(sources=sources)


def test_failed_lms_refresh_returns_dated_cache_without_fresh_alert(monkeypatch):
    from app.services.scanner import ScanResult

    monkeypatch.setattr(
        update, "scan_all", lambda: [ScanResult("SWE341", None, [], "LMS_SESSION_EXPIRED")]
    )
    cached = {
        "remote_id": "117",
        "title": "Homework",
        "course_code": "SWE341",
        "due_at": "2026-10-21T18:00:00+03:00",
        "checked_at": "2026-10-18T10:00:00+00:00",
        "url": "https://lms.altinbas.edu.tr/web/Uzem",
    }
    monkeypatch.setattr(
        update,
        "stored_section",
        lambda name, code: {"items": [cached] if name == "assignments" else []},
    )
    monkeypatch.setattr(update, "new_alerts", lambda items: [])
    result = update.university_update(sources=["LMS"])
    section = next(
        section
        for section in result["sections"]
        if section["section"].endswith("cached:assignments")
    )
    assert section["freshness"] == "STALE"
    assert section["items"][0]["scanned_at"] == cached["checked_at"]
    assert result["completeness"] == "PARTIAL"


def test_bounded_response_keeps_counts_and_detail_sources(monkeypatch):
    def reader(**kwargs):
        return {
            "scanned_at": "2026-10-19T00:00:00+03:00",
            "scan_errors": {},
            "scanned_sections": ["notifications"],
            "baseline_sections": [],
            "changes": [],
            "current": {
                "notifications": [{"remote_id": str(i), "title": "Notice"} for i in range(10)]
            },
        }

    monkeypatch.setattr(update, "ewi_updates", reader)
    monkeypatch.setattr(update, "new_alerts", lambda items: [])
    result = update.university_update(sources=["EWI"], max_items_per_section=2)
    assert result["response_has_more"]
    section = result["sections"][0]
    assert section["item_count"] == 10 and len(section["items"]) == 2


def test_body_cancellation_is_a_notice_and_negation_is_not_cancellation():
    notice = update.cancellation_notices(
        [
            {
                "status": "UPDATED",
                "item": {
                    "title": "Schedule update",
                    "content": "Tomorrow's class is cancelled.",
                    "url": "https://example.test/source",
                },
            }
        ]
    )[0]
    assert notice["status"] == "CANCELLATION_NOTICE" and notice["confidence"].startswith("Low")
    assert "cancelled" in notice["evidence"] and notice["source_url"]
    assert update.cancellation_notices([{"item": {"title": "Class will not be cancelled."}}]) == []


def test_large_derived_summary_reports_truncation_and_keeps_source_ids(monkeypatch):
    monkeypatch.setattr(update, "scan_all", list)
    monkeypatch.setattr(update, "new_alerts", lambda items: [])
    conflicts = [
        {"source_url": "https://example.test/source", "remote_id": str(i)} for i in range(600)
    ]
    monkeypatch.setattr(update, "timeline_and_conflicts", lambda sections: ([], conflicts))
    result = update.university_update(sources=["LMS"])
    assert result["summary_counts"]["conflicts"] == 600
    assert len(result["conflicts"]) == result["summary_limit"] == 500
    assert result["response_has_more"]
    assert result["conflicts"][-1]["remote_id"] == "499"
    assert result["conflicts"][-1]["source_url"]
