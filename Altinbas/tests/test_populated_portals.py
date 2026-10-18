"""Real Chromium parsing against offline populated pages; no university traffic."""

import json
from contextlib import contextmanager

import pytest

from app.ewi import portal as ewi
from app.lms import scanner
from app.lms.auth import is_authenticated
from app.lms.courses import Course
from app.lms.readonly import iter_pages, request_allowed
from app.uzem import portal as uzem

EWI_NAV = '<a href="/web/Ogrenci/Dersler/Derslerim">My Courses</a>'
UZEM_NAV = '<div id="user-menu">User</div>'


def test_populated_lms_resources_exams_and_download_links(offline):
    _, page, routes = offline
    course = Course(
        "SWE431",
        "Testing",
        "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=7",
        "Fall 2026/2027",
    )
    resource_url = "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersKaynaklari?Action=Details&SID=7&CRID=2"
    routes[
        course.url
    ] = """<div class="yoo-card"><h2>Course Resources</h2><table><thead><tr><th>Resource Title</th></tr></thead>
    <tbody><tr onclick="DersKaynaklari?Action=Details&SID=7&CRID=2"><td>Lecture 1</td><td>Instructor</td><td>1</td><td>15.10.2026</td></tr></tbody></table></div>
    <div class="yoo-card"><h2>Exam Information</h2><div class="yoo-card-body">Midterm 05.11.2026 13:00 Room A</div></div>"""
    routes[
        resource_url
    ] = f'''<div class="uzem-resource-meta"><div class="uzem-resource-description"><p>Material</p></div></div>
    <table><thead><tr><th>File Name</th></tr></thead><tbody><tr><td>lecture.pdf</td><td>100 KB</td><td>15.10.2026</td>
    <td><a title="Download File" href="{resource_url}&DownloadFile=9">Download</a></td></tr></tbody></table>'''
    page.goto(course.url)
    resources = scanner._resources(page, course)
    assert resources[0].file_count == 1
    assert "05.11.2026" in scanner._exams(page)[0]["raw_text"]
    detail = scanner._resource_details(page, course, resources[0])
    assert detail.files[0].remote_id == "9"


def test_explicit_exam_table_fields_and_unknown_date(offline):
    _, page, routes = offline
    url = "https://lms.altinbas.edu.tr/web/Uzem"
    routes[url] = """<div class="yoo-card"><h2>Exam Information</h2><table>
    <thead><tr><th>Exam Name</th><th>Exam Date</th><th>Weight</th><th>Location</th></tr></thead>
    <tbody><tr><td>Midterm</td><td>05.11.2026 13:00</td><td>30%</td><td>Room A</td></tr>
    <tr><td>Final</td><td>Not announced yet</td><td>50%</td><td>Unknown</td></tr></tbody>
    </table></div>"""
    page.goto(url)
    midterm, final = scanner._exams(page)
    assert midterm["date"] == "2026-11-05T13:00:00+03:00"
    assert midterm["weight"] == "30%" and midterm["location"] == "Room A"
    assert midterm["source_url"] == url
    assert final["date"] is None and final["date_status"] == "Unknown"


def test_ewi_populated_paginated_notifications_and_blank_grades(offline, monkeypatch):
    context, _, routes = offline
    url = ewi.BASE + ewi.NOTIFICATIONS_PATH

    def notifications(text, next_link=""):
        return (
            EWI_NAV
            + f"""<table><thead><tr><th>Notification</th><th>Date</th></tr></thead><tbody>
        <tr><td>{text}</td><td>15.10.2026 10:00</td></tr></tbody></table>{next_link}"""
        )

    # Real EWI pager links mistakenly target /web/Main. The reader preserves section path.
    routes[url] = notifications(
        "New exam",
        '<ul class="pagination"><li><a href="https://ewi.altinbas.edu.tr/web/Main?ShowPage=2">keyboard_arrow_right</a></li></ul>',
    )
    routes[url + "?ShowPage=2"] = notifications("Room changed")
    routes[ewi.BASE + ewi.RESULTS_PATH] = (
        EWI_NAV
        + """<table><thead><tr><th>Course Code</th><th>Letter grade</th></tr></thead><tbody>
    <tr><td>SWE431</td><td>AA</td></tr><tr><td>IE208</td><td></td></tr></tbody></table>"""
    )

    @contextmanager
    def fake_context(*args, **kwargs):
        yield context

    monkeypatch.setattr(ewi, "authenticated_context", fake_context)
    assert [item["notification"] for item in ewi.get_notifications()] == [
        "New exam",
        "Room changed",
    ]
    assert ewi.get_exam_results()[1]["values"][1] == ""
    assert not is_authenticated(context.pages[0])


def test_uzem_populated_grades_and_notifications_do_not_open_actions(offline):
    context, page, routes = offline
    courses = [{"id": 1, "name": "SWE431 Testing"}]
    routes[f"https://{uzem.HOST}/grade/report/user/index.php?id=1"] = (
        UZEM_NAV
        + """<table class="user-grade"><tr><th>Item</th><th>Weight</th><th>Grade</th></tr>
    <tr><th>Midterm</th><td>30%</td><td>84</td><td>0-100</td><td>84%</td></tr>
    <tr><th>Final</th><td>70%</td><td>-</td></tr></table>"""
    )
    routes[f"https://{uzem.HOST}/message/output/popup/notifications.php"] = (
        UZEM_NAV
        + """<div data-region="notification-area"><div data-region="control-area">
    <div data-region="notification-item-container"><a href="/message/mark.php?sesskey=private">Do not follow</a><time datetime="2026-10-15T10:00:00+03:00">Today</time></div></div></div>"""
    )
    grades = uzem._grades(page, courses)
    assert grades[0]["rows"][0]["grade"] == "84"
    assert grades[0]["rows"][1]["grade"] == "-"
    assert uzem._notifications(page)[0]["url"] is None
    assert context._readonly_blocked == []


def test_browser_guard_blocks_form_submit_and_mark_read(offline):
    context, page, routes = offline
    url = "https://uzem.altinbas.edu.tr/course/view.php?id=1"
    routes[url] = UZEM_NAV
    page.goto(url)
    outcome = page.evaluate("""async () => {
      const blocked = [];
      for (const [url, options] of [['/message/mark.php?sesskey=secret', {}], ['/submit.php', {method:'POST',body:'x=1'}]]) {
        try { await fetch(url, options); blocked.push(false); } catch { blocked.push(true); }
      }
      return blocked;
    }""")
    assert outcome == [True, True]
    assert len(context._readonly_blocked) == 2


def test_only_observed_read_rpcs_allowed_and_mixed_batch_rejected():
    url = "https://uzem.altinbas.edu.tr/lib/ajax/service.php?sesskey=not-logged"
    allowed = {
        "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
        "args": {"classification": "all", "offset": 0},
    }
    assert request_allowed("POST", url, post_data=json.dumps([allowed]))
    assert not request_allowed(
        "POST",
        url,
        post_data=json.dumps(
            [allowed, {"methodname": "core_message_mark_notification_read", "args": {}}]
        ),
    )
    assert not request_allowed(
        "POST", url, post_data=json.dumps([{**allowed, "args": {"markread": True}}])
    )


def test_pagination_rejects_external_next_and_repeated_url(offline):
    _, page, routes = offline
    url = ewi.BASE + ewi.NEWS_PATH
    routes[url] = EWI_NAV + '<a rel="next" href="https://evil.test/">Next</a>'
    page.goto(url)
    with pytest.raises(RuntimeError, match="PAGINATION_LINK_REJECTED"):
        list(iter_pages(page))


def test_unknown_layouts_fail_but_recognized_empty_tables_succeed(offline, monkeypatch):
    context, page, routes = offline

    @contextmanager
    def fake(*args, **kwargs):
        yield context

    monkeypatch.setattr(ewi, "authenticated_context", fake)
    for path, reader in [
        (ewi.SCHEDULE_PATH, ewi.get_schedule),
        (ewi.RESULTS_PATH, ewi.get_exam_results),
        (ewi.ABSENCE_PATH, ewi.get_absences),
        (ewi.RESOURCES_PATH, ewi.get_course_resources),
    ]:
        routes[ewi.BASE + path] = EWI_NAV + "<h1>Changed layout</h1>"
        with pytest.raises(RuntimeError, match="LAYOUT_CHANGED"):
            reader()
    routes[ewi.BASE + ewi.RESULTS_PATH] = (
        EWI_NAV
        + "<table><thead><tr><th>Course Code</th><th>Letter grade</th></tr></thead><tbody></tbody></table>"
    )
    assert ewi.get_exam_results() == []
    routes[f"https://{uzem.HOST}/grade/report/user/index.php?id=1"] = UZEM_NAV
    with pytest.raises(RuntimeError, match="UZEM_GRADE_LAYOUT_CHANGED"):
        uzem._grades(page, [{"id": 1, "name": "Synthetic course"}])


def test_ewi_schedule_reads_explicit_next_page(offline, monkeypatch):
    context, _, routes = offline

    @contextmanager
    def fake(*args, **kwargs):
        yield context

    monkeypatch.setattr(ewi, "authenticated_context", fake)
    url = ewi.BASE + ewi.SCHEDULE_PATH

    def schedule(code, next_link=""):
        return (
            EWI_NAV
            + f'<div class="yoo-post yoo-style3"><div class="yoo-post-user-name">16.10.2026</div><div class="yoo-post-user-email">Friday</div><div class="dp-row"><div>{code} Synthetic course</div><div>10:00-11:00 (A)</div></div></div>{next_link}'
        )

    routes[url] = schedule("SWE431", '<a rel="next" href="?page=2">Next</a>')
    routes[url + "?page=2"] = schedule("IE208")
    assert [item["course_code"] for item in ewi.get_schedule()] == ["SWE431", "IE208"]


def test_calendar_json_survives_broken_portal_javascript(offline):
    _, page, routes = offline
    url = "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=7"
    events = [
        {
            "id": "DP-1",
            "title": "Course",
            "start": "2026-10-16T08:30:00",
            "end": "2026-10-16T12:30:00",
            "extendedProps": {"description": "D602"},
        },
        {
            "id": "DP-2",
            "title": "Course",
            "start": "2026-10-16T14:00:00",
            "end": "2026-10-16T16:00:00",
        },
    ]
    routes[url] = (
        '<div class="yoo-card"><h2>Course Calendar</h2><div id="UzemCourseCalendar"></div></div><script>const CalendarElement=document.getElementById("UzemCourseCalendar"); const c=new FullCalendar.Calendar(CalendarElement, {events: '
        + json.dumps(events)
        + "}); invalid script !!! </script>"
    )
    page.goto(url)
    scope, parsed = scanner._calendar(page)
    assert "Embedded LMS calendar JSON" in scope
    assert [event.time for event in parsed] == ["08:30-12:30", "14:00-16:00"]
    assert parsed[0].description == "D602"
    assert parsed[0].location == ""
    assert parsed[0].remote_id == "DP-1"
    routes[url] = routes[url].replace(json.dumps(events), "[untrustedFunction()]")
    page.goto(url)
    with pytest.raises(RuntimeError, match="CALENDAR_PAYLOAD_INVALID"):
        scanner._calendar(page)
