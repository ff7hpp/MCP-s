"""Observed assignment list and detail DOM. Never interacts with submission forms."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from app.errors import ActionableError
from app.lms.models import Assignment, RemoteFile
from app.lms.readonly import iter_pages, request_allowed

PATH = "/web/Uzem/Ogrenci/Dersler/Odevler"
ISTANBUL = timezone(timedelta(hours=3))


def assignment_url(url: str, sid: str) -> tuple[str, str]:
    query = parse_qs(urlparse(url).query)
    if (
        not request_allowed("GET", url, navigation=True)
        or urlparse(url).path != PATH
        or query.get("Action") != ["Details"]
        or query.get("SID") != [sid]
        or set(query) != {"Action", "SID", "OdevID"}
    ):
        raise ActionableError("ASSIGNMENT_LINK_INVALID: course or assignment identity changed")
    return url, query["OdevID"][0]


def _fields(container) -> dict[str, str]:
    fields = {}
    for group in container.locator(".form-group").all():
        if group.locator("strong").count() == 1 and group.locator("p").count() == 1:
            fields[group.locator("strong").inner_text().strip()] = (
                group.locator("p").inner_text().strip()
            )
    return fields


def _files(page, selector: str, assignment: Assignment, sid: str) -> list[RemoteFile] | None:
    table = page.locator(selector)
    if not table.count():
        return None
    files = []
    for row in table.locator("tbody tr").all():
        cells = row.locator("td").all_inner_texts()
        if len(cells) == 1 and row.locator("td[colspan]").count():
            continue
        if len(cells) < 3:
            raise ActionableError("ASSIGNMENT_FILE_LAYOUT_CHANGED")
        links = row.locator('a[href*="DownloadFile="]')
        url = urljoin(page.url, links.first.get_attribute("href") or "") if links.count() else ""
        query = parse_qs(urlparse(url).query)
        if (
            not request_allowed("GET", url, navigation=True)
            or urlparse(url).path != PATH
            or query.get("SID") != [sid]
            or query.get("OdevID") != [assignment.remote_id]
            or "DownloadFile" not in query
        ):
            raise ActionableError("ASSIGNMENT_FILE_LINK_INVALID")
        files.append(
            RemoteFile(
                cells[0].strip(), cells[1].strip(), cells[2].strip(), url, query["DownloadFile"][0]
            )
        )
    return files


def _timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M").replace(tzinfo=ISTANBUL).isoformat()
    except ValueError:
        return None


def read_detail(
    page, assignment: Assignment, sid: str, course_code: str | None = None
) -> Assignment:
    assignment_url(assignment.url, sid)
    page.goto(assignment.url, wait_until="domcontentloaded", timeout=30000)
    _, observed_id = assignment_url(page.url, sid)
    if observed_id != assignment.remote_id:
        raise ActionableError("ASSIGNMENT_DETAILS_ID_MISMATCH")
    if page.locator(".uzem-odev-language-fields").count() != 1:
        raise ActionableError("ASSIGNMENT_DETAILS_NOT_FOUND: page scan failed")
    reference = page.locator(".uzem-academic-course-reference").first
    if not reference.count() or (
        course_code and not reference.inner_text().strip().startswith(course_code + " -")
    ):
        raise ActionableError("ASSIGNMENT_DETAILS_LAYOUT_CHANGED")
    fields = _fields(page.locator(".uzem-odev-common-fields"))
    instructions, titles = {}, {}
    for column in page.locator(".uzem-odev-language-column").all():
        language = column.locator(".uzem-odev-language-title").inner_text().strip()
        values = _fields(column)
        if values.get("Assignment Description"):
            instructions[language] = values["Assignment Description"]
        if values.get("Assignment Name"):
            titles[language] = values["Assignment Name"]
    submission = page.locator(".yoo-card").filter(
        has=page.locator("h2", has_text="My Submission Files")
    )
    attachments = _files(page, "#table_UZEM_StudentOdevTeacherFiles", assignment, sid)
    # The current portal uses SubmissionFiles; retain the older observed layout.
    submitted = _files(
        page,
        "#table_UZEM_StudentOdevSubmissionFiles, #table_UZEM_StudentOdevFiles",
        assignment,
        sid,
    )
    if (
        submission.count() == 1
        and submission.locator(".uzem-course-empty-row")
        .filter(has_text="No files have been submitted yet.")
        .count()
    ):
        submitted = []
    if attachments is None:
        teacher = page.locator(".uzem-odev-files").filter(
            has=page.locator("h3", has_text="Assignment Files")
        )
        if teacher.locator(".uzem-course-empty-row").count():
            attachments = []
    values = {
        "start_at": fields.get("Start Date") or None,
        "end_at": fields.get("End Date") or None,
        "effective_due_at": fields.get("Effective Due Date") or None,
        "status": fields.get("Status") or None,
        "submission_status": fields.get("Submission Status") or None,
        "attachments": attachments,
        "submitted_files": submitted,
        "instructions": instructions,
    }
    values["due_at"] = _timestamp(values["effective_due_at"] or values["end_at"])
    states = {
        key: "Confirmed" if value is not None and value != {} else "Unknown"
        for key, value in values.items()
    }
    return replace(
        assignment,
        title=titles.get("English Content") or assignment.title,
        checked_at=datetime.now(UTC).isoformat(),
        field_status=states,
        **values,
    )


def read_assignments(page, course, errors: dict[str, str]) -> list[Assignment]:
    sid = parse_qs(urlparse(course.url).query)["SID"][0]
    url = f"https://lms.altinbas.edu.tr{PATH}?Action=List&SID={sid}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    assignments, seen = [], set()
    try:
        for _ in iter_pages(page):
            table = page.locator("#table_UZEM_StudentOdevList")
            if table.count() != 1:
                # Empty is accepted only with the observed explicit empty-state element.
                empty = page.locator(".yoo-content .uzem-course-empty-row")
                if empty.count() and "assignment" in empty.inner_text().casefold():
                    continue
                raise ActionableError("ASSIGNMENT_LIST_LAYOUT_CHANGED: page scan failed")
            for index, row in enumerate(table.locator("tbody tr").all()):
                try:
                    cells = [text.strip() for text in row.locator("td").all_inner_texts()]
                    if row.locator("td[colspan]").count() and len(cells) == 1:
                        if "no " in cells[0].casefold():
                            continue
                        raise ActionableError("ASSIGNMENT_LIST_LAYOUT_CHANGED")
                    if len(cells) < 7:
                        raise ActionableError("ASSIGNMENT_LIST_LAYOUT_CHANGED")
                    link = row.locator('a[href*="OdevID="]').first
                    if not link.count():
                        raise ActionableError("ASSIGNMENT_LINK_MISSING")
                    href, remote_id = assignment_url(
                        urljoin(page.url, link.get_attribute("href") or ""), sid
                    )
                    if remote_id in seen:
                        raise ActionableError("DUPLICATE_ASSIGNMENT_ID")
                    seen.add(remote_id)
                    assignments.append(
                        Assignment(
                            remote_id,
                            cells[0],
                            href,
                            cells[2] or None,
                            cells[3] or None,
                            status=cells[4] or None,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
                    errors[f"assignments:row:{index}"] = (
                        f"ASSIGNMENT_LIST_ITEM_FAILED: {type(exc).__name__}"
                    )
    except Exception as exc:
        if not assignments:
            raise
        errors["assignments:list"] = f"LIST_PAGINATION_FAILED: {type(exc).__name__}"
    detailed = []
    for item in assignments:
        try:
            detailed.append(read_detail(page, item, sid, course.course_code))
        except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
            error = f"ASSIGNMENT_DETAIL_FAILED: {item.remote_id}: {type(exc).__name__}"
            errors[f"assignments:{item.remote_id}"] = error
            detailed.append(
                replace(
                    item,
                    detail_error=error,
                    checked_at=datetime.now(UTC).isoformat(),
                    field_status={
                        name: "Page scan failed"
                        for name in (
                            "due_at",
                            "submission_status",
                            "attachments",
                            "submitted_files",
                            "instructions",
                        )
                    },
                )
            )
    return detailed
