"""Daily workflow, local acknowledgments, network recovery and report boundaries."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import cli
from app.config import Config
from app.services import daily
from app.storage import state


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "LOCK_PATH", tmp_path / "operation.lock")
    monkeypatch.setattr(daily, "STATE_PATH", tmp_path / "daily.json")
    monkeypatch.setattr(daily, "REPORTS", tmp_path / "reports")
    config = Config(
        term="Fall 2026/2027",
        drive_root=tmp_path,
        cloud_account="ff7hpp@gmail.com",
        cloud_university_id="university123",
    )
    monkeypatch.setattr(daily, "load_config", lambda: config)
    (tmp_path / "University").mkdir()
    result = {
        "requested_sources": ["LMS", "EWI", "UZEM"],
        "scanned_at": "2026-10-19T09:00:00+00:00",
        "source_status": {s: {"status": "Confirmed"} for s in ("LMS", "EWI", "UZEM")},
        "sections": [],
        "changes": [],
        "alerts": [],
        "timeline": [],
        "errors": {},
    }
    monkeypatch.setattr(daily, "university_update", lambda **kwargs: deepcopy(result))
    return result, config


def test_repeat_changes_are_not_notified_and_acknowledgment_stays_local(setup):
    result, _ = setup
    result["changes"] = [
        {
            "source": "LMS",
            "type": "announcement",
            "status": "NEW",
            "course": "SWE341",
            "name": "Lecture",
            "scanned_at": "first",
        }
    ]
    first = daily.daily_update(sync_files=False)
    assert first["notify"] and len(first["announcements"]) == 1
    result["changes"][0]["scanned_at"] = "second"
    second = daily.daily_update(sync_files=False)
    assert not second["notify"] and second["changes"] == []
    assert Path(first["report_path"]).is_file()
    assert daily.daily_status()["last_success"]


def test_explicit_today_query_retains_change_after_silent_scheduled_scan(setup):
    result, _ = setup
    result["changes"] = [
        {
            "source": "LMS",
            "type": "announcement",
            "status": "NEW",
            "course": "SWE341",
            "name": "Retained lecture notice",
        }
    ]
    daily.daily_update(sync_files=False)
    result["changes"] = []
    assert not daily.daily_update(sync_files=False)["notify"]
    assert "Retained lecture notice" in daily.natural_request("ما الجديد اليوم؟")
    assert "Retained lecture notice" in daily.natural_request("اعرض تغييرات SWE341")


def test_retry_only_transient_source_and_preserve_first_changes(setup, monkeypatch):
    result, _ = setup
    initial = deepcopy(result)
    initial["errors"] = {"EWI": "EWI_PORTAL_UNAVAILABLE", "UZEM": "UZEM_SESSION_EXPIRED"}
    initial["changes"] = [{"source": "LMS", "status": "NEW", "name": "first"}]
    retried = deepcopy(result)
    retried["sections"] = [{"source": "EWI", "section": "news", "items": []}]
    calls = []

    def scan(**kwargs):
        calls.append(kwargs)
        return initial if len(calls) == 1 else retried

    monkeypatch.setattr(daily, "university_update", scan)
    monkeypatch.setattr(daily.time, "sleep", lambda seconds: None)
    output = daily._scan_with_retry()
    assert calls[1]["sources"] == ["EWI"]
    assert output["errors"] == {"UZEM": "UZEM_SESSION_EXPIRED"}
    assert len(output["changes"]) == 1


def test_mount_disconnect_then_recovery_retains_last_success(setup, monkeypatch):
    first = daily.daily_update(sync_files=False)
    assert first["status"] == "COMPLETE_IN_SCANNED_SCOPES"
    success = daily.daily_status()["last_success"]
    monkeypatch.setattr(daily.university, "prepare_sync", Mock(side_effect=OSError("offline")))
    monkeypatch.setattr(daily.uzem_sync, "prepare_sync", Mock(return_value=[]))
    monkeypatch.setattr(daily.university, "execute_sync", lambda items, **kwargs: items)
    failed = daily.daily_update()
    assert failed["status"] == "PARTIAL" and "SYNC:LMS" in failed["errors"]
    assert daily.daily_status()["last_success"] == success
    monkeypatch.setattr(daily.university, "prepare_sync", lambda **kwargs: ([], []))
    assert daily.daily_update()["status"] == "COMPLETE_IN_SCANNED_SCOPES"


def test_failure_and_cancellation_record_only_safe_error_code(setup, monkeypatch):
    monkeypatch.setattr(
        daily, "_scan_with_retry", Mock(side_effect=RuntimeError("password=secret"))
    )
    with pytest.raises(RuntimeError):
        daily.daily_update(sync_files=False)
    assert "secret" not in daily.STATE_PATH.read_text()
    assert daily.daily_status()["status"] == "FAILED"
    monkeypatch.setattr(daily, "_scan_with_retry", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        daily.daily_update(sync_files=False)
    assert daily.daily_status()["status"] == "CANCELLED"


def test_natural_commands_only_explicit_file_update_syncs(setup, monkeypatch):
    calls = []
    actual = daily.daily_update

    def run(**kwargs):
        calls.append(kwargs["sync_files"])
        return actual(sync_files=False)

    monkeypatch.setattr(daily, "daily_update", run)
    for request in (
        "ما الجديد اليوم؟",
        "ما واجباتي القادمة؟",
        "اعرض تغييرات SWE341",
        "حدّث ملفات الجامعة",
    ):
        assert "# مركز الجامعة" in daily.natural_request(request)
    assert calls == [False, False, False, True]
    with pytest.raises(RuntimeError, match="REQUEST_UNKNOWN"):
        daily.natural_request("send assignment")


def test_report_publish_requires_current_readbacks_and_never_overwrites(setup, monkeypatch):
    _, config = setup
    daily.daily_update(sync_files=False)
    with pytest.raises(RuntimeError, match="MISMATCH"):
        daily.publish_report("wrong@example.test", config.cloud_university_id)
    stored = state.load_state(daily.STATE_PATH)
    stored["verification_rows"] = [{"row": {}, "path": "fixture"}]
    state.save_state(daily.STATE_PATH, stored)
    monkeypatch.setattr(
        daily.cloud, "verification_status", lambda *args: {"cloud_verified_at": "2020"}
    )
    with pytest.raises(RuntimeError, match="READBACK_PENDING"):
        daily.publish_report(config.cloud_account, config.cloud_university_id)
    monkeypatch.setattr(
        daily.cloud, "verification_status", lambda *args: {"cloud_verified_at": "2099"}
    )
    published = daily.publish_report(config.cloud_account, config.cloud_university_id)
    assert published["cloud_verification"] == daily.cloud.PENDING
    target = Path(published["path"])
    assert target.is_file()
    daily.publish_report(config.cloud_account, config.cloud_university_id)
    target.write_text("original user file")
    with pytest.raises(RuntimeError, match="TARGET_EXISTS"):
        daily.publish_report(config.cloud_account, config.cloud_university_id)
    assert target.read_text() == "original user file"


def test_report_content_escapes_html_and_removes_secret_url_parameters(setup):
    source, _ = setup
    source["changes"] = [
        {
            "source": "LMS",
            "status": "NEW",
            "name": "<script>x</script> password=hidden",
            "source_url": "https://lms.altinbas.edu.tr/web/Uzem?SID=1&token=hidden",
        }
    ]
    result = daily.daily_update(sync_files=False)
    text = daily.render_report(result)
    assert "<script>" not in text and "hidden" not in text and "SID=1" in text
    assert "token=" not in text


def test_wrong_account_blocks_all_sync_before_portal_transfer(setup, monkeypatch):
    _, config = setup
    monkeypatch.setattr(
        daily, "load_config", lambda: replace(config, cloud_account="wrong@test.example")
    )
    prepare = Mock()
    monkeypatch.setattr(daily.university, "prepare_sync", prepare)
    assert daily.daily_update()["errors"]["DRIVE"] == "CLOUD_DESTINATION_UNKNOWN"
    prepare.assert_not_called()


def test_hidden_same_metadata_content_change_is_updated(setup, monkeypatch):
    from types import SimpleNamespace

    _, config = setup
    old = config.drive_root / "University" / "old.pdf"
    old.write_bytes(b"old bytes")
    new = old.with_name("new-revision.pdf")
    item = SimpleNamespace(
        comparison=SimpleNamespace(status="PRESENT", existing=old, filename="old.pdf"),
        row={"course_code": "SWE341"},
        downloaded_to=None,
        error=None,
        to_dict=lambda: {"status": "PRESENT"},
    )
    monkeypatch.setattr(daily.university, "prepare_sync", lambda **kwargs: ([item], []))
    monkeypatch.setattr(daily.uzem_sync, "prepare_sync", lambda **kwargs: [])

    def execute(items, **kwargs):
        if items:
            new.write_bytes(b"new bytes")
            item.downloaded_to = item.comparison.existing = new
        return items

    monkeypatch.setattr(daily.university, "execute_sync", execute)
    result = daily.daily_update()
    assert result["files"][0]["status"] == "UPDATED" and result["notify"]
    assert old.read_bytes() == b"old bytes"


def test_daily_cli_quiet_is_silent_without_change(setup, capsys):
    assert cli.main(["daily-update", "--no-sync", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert cli.main(["ask", "ما واجباتي القادمة؟"]) == 0
    assert "الواجبات القادمة" in capsys.readouterr().out
    assert cli.main(["ما واجباتي القادمة؟"]) == 0
    assert "الواجبات القادمة" in capsys.readouterr().out


def test_new_errors_notify_once_without_repeating(setup):
    result, _ = setup
    result["errors"] = {"EWI": "EWI_SESSION_EXPIRED: manual sign-in"}
    assert daily.daily_update(sync_files=False)["notify"]
    assert not daily.daily_update(sync_files=False)["notify"]


def test_unknown_assignment_detail_stays_visible(setup):
    result, _ = setup
    result["sections"] = [
        {
            "source": "LMS",
            "section": "SWE341:assignments",
            "items": [
                {
                    "data": {
                        "course_code": "SWE341",
                        "remote_id": "118",
                        "title": "Homework",
                        "detail_error": "FAILED",
                    },
                    "source_url": "https://lms.altinbas.edu.tr/web/Uzem",
                    "freshness": "STALE",
                }
            ],
        }
    ]
    output = daily.daily_update(sync_files=False)
    assert output["assignments"][0]["date_status"] == "Unknown"
    assert output["assignments"][0]["freshness"] == "STALE"


def test_overlapping_daily_process_cannot_scan_or_change_run(setup):
    import subprocess
    import sys

    code = "from pathlib import Path; from app.storage.state import operation_lock; import sys,time;\nwith operation_lock(Path(sys.argv[1])):\n print('LOCKED',flush=True); time.sleep(30)"
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(state.LOCK_PATH)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="SCAN_BUSY"):
            daily.daily_update(sync_files=False)
        assert not daily.STATE_PATH.exists()
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_supervisor_cancels_only_owned_process_and_records_timeout(setup, monkeypatch):
    from tasks import run_daily

    child = Mock(pid=12345)
    child.wait.side_effect = [run_daily.subprocess.TimeoutExpired("fixture", 900), 0]
    monkeypatch.setattr(run_daily.subprocess, "Popen", Mock(return_value=child))
    kill = Mock()
    monkeypatch.setattr(run_daily.subprocess, "run", kill)
    assert run_daily.main() == 124
    if run_daily.os.name == "nt":
        assert kill.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    assert daily.daily_status()["status"] == "CANCELLED"


def test_report_readback_uses_same_sha256_boundary(setup, monkeypatch):
    _, config = setup
    daily.daily_update(sync_files=False)
    published = daily.publish_report(config.cloud_account, config.cloud_university_id)
    monkeypatch.setattr(daily.cloud, "READBACK_DIRECTORY", config.drive_root / "readbacks")
    monkeypatch.setattr(daily.cloud, "PROJECT_ROOT", config.drive_root)
    monkeypatch.setattr(daily.cloud, "STATE_PATH", config.drive_root / "cloud.json")
    readback = daily.cloud.READBACK_DIRECTORY / "report.md"
    readback.parent.mkdir()
    path = Path(published["path"])
    readback.write_bytes(path.read_bytes())
    evidence = {
        "account": config.cloud_account,
        "listed_file_id": "report123",
        "readback_file_id": "report123",
        "listed_name": path.name,
        "listed_size": path.stat().st_size,
        "folder_id": config.cloud_university_id,
        "ancestor_ids": [],
        "readback_parent_ids": [config.cloud_university_id],
    }
    receipt = daily.verify_report(readback, evidence)
    assert receipt["cloud_verification"] == "VERIFIED_AT_RECORDED_TIME"
    assert daily.daily_status()["last_cloud_success"]
    readback.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="METADATA_MISMATCH"):
        daily.verify_report(readback, evidence)
