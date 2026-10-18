from app import cli


def test_lms_sync_defaults_to_preview_and_execute_is_explicit(monkeypatch, capsys):
    requests, executions = [], []

    def prepare(course, *, force_refresh):
        requests.append(force_refresh)
        return [], []

    monkeypatch.setattr(cli, "prepare_sync", prepare)
    monkeypatch.setattr(cli, "execute_sync", lambda items, **kwargs: executions.append(items))
    assert cli.main(["sync", "--json"]) == 0
    assert requests == [False] and executions == []
    assert '"dry_run": true' in capsys.readouterr().out
    assert cli.main(["sync", "--execute", "--json"]) == 0
    assert requests == [False, True] and len(executions) == 1


def test_scan_all_text_reports_partial_sections(monkeypatch, capsys):
    from app.services.scanner import ScanResult

    monkeypatch.setattr(
        cli,
        "scan_all",
        lambda: [ScanResult("SWE341", None, [], section_errors={"assignments": "DETAIL_FAILED"})],
    )
    assert cli.main(["scan-all"]) == 1
    output = capsys.readouterr().out
    assert "DETAIL_FAILED" in output and "1 errors" in output
    assert "No changes" not in output


def test_single_course_json_returns_failure_on_partial_scan(monkeypatch, capsys):
    from app.lms.courses import Course
    from app.lms.models import CourseSnapshot
    from app.services.scanner import ScanResult

    snapshot = CourseSnapshot(
        course=Course("SWE341", "Testing", "https://example.test/course", "Fall 2026/2027"),
        weekly_hours={},
        resources=[],
        announcements=[],
        exams=[],
        calendar_events=[],
        calendar_scope="Current scope",
        section_errors={"assignments": "DETAIL_FAILED"},
    )
    monkeypatch.setattr(cli, "scan_one", lambda code: ScanResult(code, snapshot, []))
    assert cli.main(["scan", "SWE341", "--json"]) == 1
    assert '"completeness": "PARTIAL"' in capsys.readouterr().out
