import os
import subprocess

import pytest
from playwright.sync_api import sync_playwright

from app.config import PROJECT_ROOT
from app.lms.readonly import protect_context, request_allowed
from app.storage import state


def test_missing_or_wrong_backup_never_resets_state(tmp_path):
    path = tmp_path / "ewi_updates.json"
    state.save_state(path, {"version": 1, "sections": {}})
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="BACKUP_NOT_FOUND"):
        state.recover_state(path, tmp_path / "backups" / "ewi_updates.json.missing.bak")
    wrong = tmp_path / "backups" / "uzem_updates.json.wrong.bak"
    wrong.parent.mkdir(exist_ok=True)
    wrong.write_text('{"version":1,"sections":{}}')
    with pytest.raises(RuntimeError, match="BACKUP_TYPE_MISMATCH"):
        state.recover_state(path, wrong)
    invalid = wrong.with_name("ewi_updates.json.invalid.bak")
    invalid.write_text('{"version":1,"sections":{"files":{"items":[]}}}')
    with pytest.raises(RuntimeError, match="STATE_INVALID"):
        state.recover_state(path, invalid)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "url",
    [
        "https://uzem.altinbas.edu.tr/login/%6cogout.php",
        "https://uzem.altinbas.edu.tr/login/%256cogout.php",
        "https://lms.altinbas.edu.tr/write.php?operation=delete",
        "https://lms.altinbas.edu.tr/web/Uzem?delete=",
        "http://lms.altinbas.edu.tr/web/Uzem",
        "https://lms.altinbas.edu.tr:444/web/Uzem",
        "https://lms.altinbas.edu.tr/web/Uzem;delete=1",
        "https://lms.altinbas.edu.tr/unobserved.js",
        "https://uzem.altinbas.edu.tr/pluginfile.php/../write.php",
    ],
)
def test_unobserved_or_encoded_requests_rejected(url):
    assert not request_allowed("GET", url)


def test_observed_ewi_news_image_is_a_narrow_passive_read():
    url = "https://ewi.altinbas.edu.tr/web/News/ReadNews/Main/GetImage?NewsID=1&FileID=2"
    assert request_allowed("GET", url)
    assert not request_allowed("GET", url, navigation=True)
    assert not request_allowed("POST", url)
    assert not request_allowed("GET", url + "&Action=Delete")
    assert not request_allowed("GET", url + "&FileID=3")


def test_websocket_never_connects_to_network():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    requests = []

    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_error(400)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    Thread(target=server.serve_forever, daemon=True).start()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")
            protect_context(context)
            page = context.new_page()
            page.evaluate(
                "port => { window.auditSocket = new WebSocket(`ws://127.0.0.1:${port}/audit`); }",
                server.server_port,
            )
            page.wait_for_timeout(100)
            assert context._readonly_blocked[0]["method"] == "WEBSOCKET"
            assert requests == []
        finally:
            browser.close()
            server.shutdown()
            server.server_close()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL deployment")
def test_private_acl_setup_removes_extra_access_and_is_repeatable(tmp_path):
    (tmp_path / "pyproject.toml").write_text("# isolated fixture")
    private = tmp_path / "data"
    private.mkdir()
    sentinel = private / "fixture.txt"
    sentinel.write_text("synthetic fixture")
    for number in range(4):
        (private / f"private-acl-backup-000{number}.json").write_text("[]")
    subprocess.run(
        ["icacls.exe", str(sentinel), "/grant", "*S-1-1-0:R"], check=True, capture_output=True
    )
    subprocess.run(
        ["icacls.exe", str(sentinel), "/deny", "*S-1-1-0:(X)"], check=True, capture_output=True
    )
    script = PROJECT_ROOT / "tasks" / "protect_private_state.ps1"
    for _ in range(2):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-File", str(script), "-Root", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
            env={
                key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"
            },
        )
        assert result.returncode == 0, result.stderr
        assert "PRIVATE_ACL_VERIFIED" in result.stdout
    assert sentinel.read_text() == "synthetic fixture"
    assert len(list(private.glob("private-acl-backup-*.json"))) == 5
    assert (private / "private-acl-backup-0000.json").exists()
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "@( (Get-Acl -LiteralPath $env:UNIVERSITY_ACL_FIXTURE).Access | Where-Object {$_.AccessControlType -eq 'Deny'} ).Count",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **{key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"},
            "UNIVERSITY_ACL_FIXTURE": str(sentinel),
        },
    )
    assert result.returncode == 0 and int(result.stdout.strip()) >= 1


def test_readonly_resource_filename_can_contain_updated_word():
    assert request_allowed(
        "GET",
        "https://uzem.altinbas.edu.tr/pluginfile.php/1/mod_resource/content/2/Updated_notes.pdf",
    )


def test_translation_rpc_allows_only_observed_read_method():
    import json
    from urllib.parse import urlencode

    call = {"methodname": "core_get_string", "args": {"stringparams": [], "lang": "en"}}

    def url(calls):
        return "https://uzem.altinbas.edu.tr/lib/ajax/service-nologin.php?" + urlencode(
            {"info": "core_get_string", "args": json.dumps(calls), "cachekey": "1"}
        )

    assert request_allowed("GET", url([call]))
    assert not request_allowed(
        "GET", url([call, {"methodname": "core_message_mark_notification_read", "args": {}}])
    )
    assert not request_allowed("GET", url([{**call, "args": {"delete": True}}]))


def test_observed_moodle_rendering_rpc_is_readonly_and_rejects_mutations():
    import json
    from urllib.parse import urlencode

    calls = [
        {
            "methodname": "core_output_load_template_with_dependencies",
            "args": {
                "component": "block_myoverview",
                "template": "main",
                "themename": "boost",
                "lang": "en",
            },
        },
        {
            "methodname": "core_output_load_fontawesome_icon_system_map",
            "args": {"themename": "boost"},
        },
        {"methodname": "core_get_string", "args": {"stringid": "courses", "lang": "en"}},
    ]
    base = "https://uzem.altinbas.edu.tr/lib/ajax/service-nologin.php?"
    url = base + urlencode({"info": "3-method-calls", "args": json.dumps(calls)})
    assert request_allowed("GET", url)
    bad = calls + [{"methodname": "core_user_update_user_preferences", "args": {}}]
    assert not request_allowed("GET", base + urlencode({"args": json.dumps(bad)}))
    assert not request_allowed(
        "GET",
        base
        + urlencode(
            {"args": json.dumps([{"methodname": calls[0]["methodname"], "args": {"delete": True}}])}
        ),
    )
    media = "https://uzem.altinbas.edu.tr/lib/ajax/service.php?info=media_videojs_get_language"
    assert request_allowed(
        "POST",
        media,
        post_data=json.dumps(
            [{"methodname": "media_videojs_get_language", "args": {"lang": "en"}}]
        ),
    )
    assert not request_allowed(
        "POST",
        media,
        post_data=json.dumps(
            [{"methodname": "media_videojs_get_language", "args": {"save": True}}]
        ),
    )


def test_legacy_fingerprint_state_without_labels_remains_readable(tmp_path):
    import json

    path = tmp_path / "ewi_updates.json"
    path.write_text(
        json.dumps(
            {"version": 1, "sections": {"grades": {"items": {"key": "hash"}, "scanned_at": "old"}}}
        )
    )
    assert state.load_state(path)["sections"]["grades"]["items"] == {"key": "hash"}


@pytest.mark.parametrize(
    "override", [{"status": "unknown"}, {"status": None}, {"size": True}, {"size": 0}]
)
def test_receipt_validation_rejects_invalid_status_and_size(override):
    record = {
        "path": "fixture.pdf",
        "revision": "r",
        "sha256": "0" * 64,
        "status": "installed",
        "size": 1,
    }
    with pytest.raises(RuntimeError, match="SYNC_STATE_INVALID"):
        state.validate_sync_record({**record, **override})


def test_legacy_receipt_without_status_remains_readable_without_rewriting(tmp_path, monkeypatch):
    from app.drive import records

    path = tmp_path / "sync_records.json"
    monkeypatch.setattr(records, "STATE_PATH", path)
    legacy = {"path": "fixture.pdf", "revision": "r", "sha256": "0" * 64, "size": 1}
    state.save_state(path, {"version": 1, "sections": {"legacy": legacy}})
    original = path.read_bytes()
    assert records.get_record("legacy") == legacy
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "name", ["sync_records.json", "syllabus_state.json", "university_alerts.json"]
)
def test_recovery_rejects_malformed_known_state_before_replacing_original(tmp_path, name):
    import json

    path = tmp_path / name
    state.save_state(path, {"version": 1, "sections": {}})
    original = path.read_bytes()
    backup = tmp_path / "backups" / (name + ".bad.bak")
    backup.parent.mkdir()
    backup.write_text(json.dumps({"version": 1, "sections": {"bad": 123}}))
    with pytest.raises(RuntimeError, match="STATE_INVALID"):
        state.recover_state(path, backup)
    assert path.read_bytes() == original
