"""Sanitized observed LMS layouts, real Chromium, no university requests."""

from dataclasses import replace

import pytest

from app.lms.announcements import news_list
from app.lms.assignments import PATH, read_assignments
from app.lms.courses import Course
from app.lms.models import CourseSnapshot
from app.lms.readonly import request_allowed
from app.lms.sections import notifications
from app.services.update import _section, timeline_and_conflicts
from app.storage import database

BASE = "https://lms.altinbas.edu.tr"
COURSE = Course(
    "SWE341",
    "Artificial intelligence",
    BASE + "/web/Uzem/Ogrenci/Dersler/DersDetay?SID=7",
    "Fall 2026/2027",
)
LIST = BASE + PATH + "?Action=List&SID=7"


def detail_url(remote_id):
    return BASE + PATH + f"?Action=Details&SID=7&OdevID={remote_id}"


def assignment_list(ids=(117, 118), extra=""):
    rows = "".join(
        f'<tr><td>HOMEWORK 1</td><td>Instructions</td><td>14.10.2026 18:00</td><td>21.10.2026 18:00</td><td>Active</td><td>No files</td><td>Teacher</td><td><a href="{detail_url(i)}">View</a></td></tr>'
        for i in ids
    )
    return f'<table id="table_UZEM_StudentOdevList"><tbody>{rows}</tbody></table>{extra}'


def assignment_detail(remote_id, end="21.10.2026 18:26", submitted=False):
    submission = (
        (
            '<table id="table_UZEM_StudentOdevFiles"><thead><tr><th>File Name</th></tr></thead><tbody>'
            f'<tr><td>answer.pdf</td><td>2 KB</td><td>20.10.2026 09:00</td><td><a href="{detail_url(remote_id)}&DownloadFile=22">Download</a></td></tr></tbody></table>'
        )
        if submitted
        else '<div class="uzem-course-empty-row">No files have been submitted yet.</div>'
    )
    return f'''<span class="uzem-academic-course-reference">SWE341 - Artificial intelligence</span>
    <div class="uzem-odev-language-fields"><div class="uzem-odev-language-column"><h3 class="uzem-odev-language-title">English Content</h3>
    <div class="form-group"><strong>Assignment Name</strong><p>HOMEWORK 1</p></div><div class="form-group"><strong>Assignment Description</strong><p>Work independently.</p></div></div></div>
    <div class="uzem-odev-common-fields"><div class="form-group"><strong>End Date</strong><p>{end}</p></div></div>
    <table id="table_UZEM_StudentOdevTeacherFiles"><tbody><tr><td>brief.pdf</td><td>4 KB</td><td>14.10.2026</td><td><a href="{detail_url(remote_id)}&DownloadFile=11">Download</a></td></tr></tbody></table>
    <div class="yoo-card"><h2>My Submission Files</h2><div class="uzem-odev-common-fields"><div class="form-group"><strong>Submission Status</strong><p>{"Submitted" if submitted else "Waiting"}</p></div></div>{submission}
    <form method="post" action="{BASE}{PATH}?Action=SetFiles&SID=7&OdevID={remote_id}"><button type="submit">Submit</button></form></div>'''


def test_duplicate_titles_preserve_ids_explicit_deadlines_and_submission(offline):
    context, page, routes = offline
    routes[LIST] = assignment_list()
    routes[detail_url(117)] = assignment_detail(117, submitted=True)
    routes[detail_url(118)] = assignment_detail(118)
    errors = {}
    items = read_assignments(page, COURSE, errors)
    assert [item.remote_id for item in items] == ["117", "118"]
    assert items[0].title == items[1].title
    assert items[0].due_at == "2026-10-21T18:26:00+03:00"
    assert items[0].submitted_files[0].name == "answer.pdf"
    assert items[1].submitted_files == []
    assert items[0].attachments[0].remote_id == "11"
    assert items[0].field_status["start_at"] == "Unknown"
    assert not errors and not context._readonly_blocked


def test_current_submission_table_preserves_upload_when_status_is_waiting(offline):
    _, page, routes = offline
    routes[LIST] = assignment_list((117,))
    routes[detail_url(117)] = assignment_detail(117, submitted=True).replace(
        'id="table_UZEM_StudentOdevFiles"',
        'id="table_UZEM_StudentOdevSubmissionFiles"',
    ).replace("<p>Submitted</p>", "<p>Waiting</p>")
    errors = {}
    item = read_assignments(page, COURSE, errors)[0]
    assert item.submission_status == "Waiting"
    assert item.submitted_files is not None
    assert item.submitted_files[0].name == "answer.pdf"
    assert item.submitted_files[0].created_at == "20.10.2026 09:00"
    assert item.field_status["submitted_files"] == "Confirmed"
    assert not errors


def test_missing_fields_unknown_and_failed_detail_does_not_hide_sibling(offline):
    _, page, routes = offline
    routes[LIST] = assignment_list()
    routes[detail_url(117)] = assignment_detail(117, end="")
    routes[detail_url(118)] = "<h1>Changed layout</h1>"
    errors = {}
    items = read_assignments(page, COURSE, errors)
    assert items[0].due_at is None and items[0].field_status["end_at"] == "Unknown"
    assert items[1].detail_error.startswith("ASSIGNMENT_DETAIL_FAILED")
    assert items[1].submitted_files is None
    assert "assignments:118" in errors


@pytest.mark.parametrize(
    "suffix",
    [
        "Action=SetFiles&SID=7&OdevID=117",
        "Action=Delete&SID=7&OdevID=117",
        "Action=Details&SID=7&OdevID=117&Operation=Delete",
        "Action=List&SID=7&OdevID=117",
        "Action=Details&SID=7&OdevID=117&OdevID=118",
        "action=Details&SID=7&OdevID=117",
        "Action=Details&SID=7&OdevID=-1",
        "Action=Details&SID=7&OdevID=117&__token=secret",
    ],
)
def test_assignment_mutations_and_ambiguous_queries_denied(suffix):
    url = BASE + PATH + "?" + suffix
    assert not request_allowed("GET", url, navigation=True)
    assert not request_allowed("POST", url)


def test_notification_redirect_and_mark_read_never_allowed():
    assert request_allowed("GET", BASE + "/web/Uzem/Notification?ShowPage=2", navigation=True)
    assert not request_allowed("GET", BASE + "/web/Uzem/Notification/Redirect?NID=1")
    assert not request_allowed("GET", BASE + "/web/Uzem/Notification/MarkAs/AllRead")
    assert not request_allowed("POST", LIST)


def test_paginated_assignment_list(offline):
    _, page, routes = offline
    routes[LIST] = assignment_list((117,), f'<a rel="next" href="{LIST}&ShowPage=2">Next</a>')
    routes[LIST + "&ShowPage=2"] = assignment_list((118,))
    for remote_id in (117, 118):
        routes[detail_url(remote_id)] = assignment_detail(remote_id)
    assert len(read_assignments(page, COURSE, {})) == 2


def test_news_explicit_empty_differs_from_changed_layout(offline):
    _, page, routes = offline
    url = BASE + "/web/Uzem/News/NewsList"
    routes[url] = (
        '<div class="yoo-content"><div class="yoo-card-body"><p>No published announcements were found.</p></div></div>'
    )
    assert news_list(page) == []
    routes[url] = "<h1>Unknown page</h1>"
    with pytest.raises(RuntimeError, match="NEWS_LIST_LAYOUT_CHANGED"):
        news_list(page)


def test_notifications_are_read_without_following_redirects(offline):
    context, page, routes = offline
    url = BASE + "/web/Uzem/Notification"
    routes[url] = (
        f'<table id="table_UZEM_NOTIFICATION_LIST"><tbody><tr class="font-weight-bold"><td><a href="{url}/Redirect?NID=77"><i>assignment</i>New homework</a></td><td>18.10.2026 10:00</td></tr></tbody></table>'
    )
    items = notifications(page)
    assert items[0]["title"] == "New homework"
    assert items[0]["unread"] is True
    assert page.url == url
    assert not context._readonly_blocked


def test_assignment_storage_partial_preserves_prior_and_identity(offline, tmp_path):
    _, page, routes = offline
    routes[LIST] = assignment_list()
    for remote_id in (117, 118):
        routes[detail_url(remote_id)] = assignment_detail(remote_id)
    items = read_assignments(page, COURSE, {})
    snapshot = CourseSnapshot(COURSE, {}, [], [], [], [], "Explicit empty", assignments=items)
    path = tmp_path / "state.sqlite"
    assert database.save_snapshot(snapshot, path) == []
    assert (
        database.save_snapshot(
            replace(snapshot, assignments=[replace(item, checked_at="later") for item in items]),
            path,
        )
        == []
    )
    updated = replace(items[0], end_at="22.10.2026 18:00", due_at="2026-10-22T18:00:00+03:00")
    changes = database.save_snapshot(
        replace(snapshot, assignments=[updated], section_errors={"assignments:118": "Failed page"}),
        path,
    )
    assert changes[0]["remote_id"] == "117" and changes[0]["status"] == "UPDATED"
    result = database.stored_section("assignments", path=path)
    assert len(result["items"]) == 2 and result["completeness"] == "PARTIAL"
    assert not any(change["status"] == "REMOVED" for change in changes)
    database.save_snapshot(replace(snapshot, assignments=[updated]), path)
    assert database.get_new_items(path)[-1]["remote_id"] == "118"


def test_assignment_deadline_overrides_matching_calendar_event():
    data = {
        "course_code": "SWE341",
        "remote_id": "117",
        "title": "HOMEWORK 1",
        "due_at": "2026-10-21T18:22:00+03:00",
    }
    sections = [
        _section("LMS", "SWE341:assignments", [data], "now", detail_url(117)),
        _section(
            "LMS",
            "SWE341:calendar_events",
            [
                {
                    "course_code": "SWE341",
                    "remote_id": "ODEV-117",
                    "date": "2026-10-20",
                    "title": "Assignment - HOMEWORK 1",
                }
            ],
            "now",
            COURSE.url,
        ),
    ]
    timeline, _ = timeline_and_conflicts(sections)
    assert len(timeline) == 1 and timeline[0]["date"] == "2026-10-21"
    assert timeline[0]["time"] == "18:22"


def test_broken_later_page_keeps_verified_assignment(offline):
    context, page, routes = offline
    routes[LIST] = assignment_list(
        (117,), '<a rel="next" href="https://untrusted.test/submit">Next</a>'
    )
    routes[detail_url(117)] = assignment_detail(117)
    errors = {}
    items = read_assignments(page, COURSE, errors)
    assert len(items) == 1 and items[0].remote_id == "117"
    assert "assignments:list" in errors
    assert not context._readonly_blocked


def test_cached_notifications_have_stable_explicit_pages(tmp_path):
    path = tmp_path / "state.sqlite"
    database.save_global_section(
        "notifications",
        [
            {"remote_id": str(i), "title": f"Notice {i}", "url": BASE + "/web/Uzem/Notification"}
            for i in range(5)
        ],
        path=path,
    )
    first = database.stored_section("notifications", path=path, offset=0, limit=2)
    second = database.stored_section(
        "notifications", path=path, offset=first["next_offset"], limit=2
    )
    assert first["total_items"] == 5 and first["has_more"]
    assert {item["remote_id"] for item in first["items"]}.isdisjoint(
        {item["remote_id"] for item in second["items"]}
    )
