"""Compare and safely copy Moodle resource files from old UZEM to Drive."""

from datetime import UTC, datetime

from app.config import Config, load_config, normalized_term, require_current_term
from app.drive.comparator import compare_file, get_drive_index
from app.errors import ActionableError
from app.services.university import SyncItem as UzemSyncItem
from app.services.university import execute_sync as execute_course_sync
from app.storage.state import serialized
from app.uzem import portal


@serialized
def prepare_sync(
    course_code: str | None = None, *, force_refresh: bool = False
) -> list[UzemSyncItem]:
    config: Config = load_config()
    if config.drive_root is None or not config.drive_root.is_dir():
        raise ValueError(
            "DRIVE_UNAVAILABLE: connect Google Drive for Desktop and configure its root"
        )
    snapshot = portal.scan_all(include_grades=False)
    courses = snapshot["courses"]
    if snapshot["scan_errors"].get("files"):
        raise ActionableError("UZEM_SCAN_INCOMPLETE: " + snapshot["scan_errors"]["files"])
    matching_ids = {
        str(course["id"])
        for course in courses
        if course_code is None
        or str(course["name"]).split(maxsplit=1)[0].casefold() == course_code.casefold()
    }
    if course_code and not matching_ids:
        raise ActionableError(f"UZEM_COURSE_NOT_FOUND: {course_code}")
    failed_courses = [
        key
        for key in snapshot["scan_errors"]
        if key.startswith("course:") and key.removeprefix("course:") in matching_ids
    ]
    if failed_courses:
        raise ActionableError(f"UZEM_SCAN_INCOMPLETE: {', '.join(failed_courses)}")
    files = snapshot["files"]
    selected = [
        row
        for row in files
        if course_code is None or str(row["course_code"]).casefold() == course_code.casefold()
    ]
    index = get_drive_index(
        config.drive_root,
        {str(row["course_code"]) for row in selected},
        source="UZEM",
        force_refresh=force_refresh,
        term=config.term,
    )
    items = []
    for row in selected:
        row = dict(row)
        row["scanned_at"] = datetime.now(UTC).isoformat()
        announced = row.get("semester")
        mapped = config.uzem_course_terms.get(str(row.get("course_id")))
        if normalized_term(announced) is None and mapped:
            row["semester"] = mapped
        require_current_term(row.get("semester"), config.term)
        items.append(UzemSyncItem(row, compare_file(row, config, source="UZEM", drive_index=index)))
    return items


def execute_sync(items: list[UzemSyncItem], *, verify_content: bool = False) -> list[UzemSyncItem]:
    return execute_course_sync(items, source="UZEM", verify_content=verify_content)
