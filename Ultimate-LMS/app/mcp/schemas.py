"""Published contracts for the shared academic and sync workflows."""

from typing import Literal, NotRequired, TypedDict


class SyncFileResult(TypedDict):
    course_code: str
    filename: str
    status: Literal["PRESENT", "MISSING", "NEW", "UPDATED", "UNKNOWN"]
    existing: str | None
    target: str
    reason: str
    downloaded_to: str | None
    error: str | None
    source: Literal["LMS", "UZEM"]
    scanned_at: str | None
    semester: str | None
    configured_term: str
    cloud_verification: Literal["PENDING_CONNECTOR_LIST_AND_READBACK", "VERIFIED_AT_RECORDED_TIME"]
    cloud_verified_at: NotRequired[str | None]
    cloud_file_id: NotRequired[str]
    cloud_folder_id: NotRequired[str]


class SyncResult(TypedDict):
    dry_run: bool
    items: list[SyncFileResult]
    scan_errors: NotRequired[dict[str, str]]


class SectionStatus(TypedDict):
    source: Literal["LMS"]
    course_code: str
    section: str
    attempted_at: str
    last_successful_at: str | None
    last_successful_scan_id: int | None
    last_attempt_scan_id: int | None
    error: str | None
    scope: str | None
    source_url: str
    scanned_at: str | None
    freshness: Literal["STALE", "UNKNOWN", "FRESH_AT_SCAN"]
    completeness: Literal["INCOMPLETE", "COMPLETE_IN_SCOPE"]
    availability: Literal["Scan failed", "Unknown", "Data available", "Not announced yet"]
    data_age_seconds: float | None


class StoredResult(TypedDict):
    source: Literal["LMS"]
    section: str
    items: list[dict[str, object]]
    sections: list[SectionStatus]
    completeness: Literal["COMPLETE_IN_SCANNED_SCOPES", "PARTIAL"]
    errors: list[str]
    next_after_change_id: NotRequired[int]
    has_more: NotRequired[bool]
    total_items: NotRequired[int]
    next_offset: NotRequired[int | None]


class FileMetadata(TypedDict):
    name: str
    size: str
    created_at: str
    download_url: str
    remote_id: str


class AssignmentItem(TypedDict):
    remote_id: str
    course_code: str
    key: str
    title: str
    url: str
    start_at: str | None
    end_at: str | None
    effective_due_at: str | None
    due_at: str | None
    instructions: dict[str, str]
    status: str | None
    submission_status: str | None
    attachments: list[FileMetadata] | None
    submitted_files: list[FileMetadata] | None
    checked_at: str | None
    scanned_at: str
    scan_id: int
    field_status: dict[str, Literal["Confirmed", "Unknown", "Page scan failed"]]
    detail_error: str | None


class AssignmentResult(TypedDict):
    source: Literal["LMS"]
    section: Literal["assignments"]
    items: list[AssignmentItem]
    sections: list[SectionStatus]
    completeness: Literal["COMPLETE_IN_SCANNED_SCOPES", "PARTIAL"]
    errors: list[str]
    has_more: NotRequired[bool]
    total_items: NotRequired[int]
    next_offset: NotRequired[int | None]


class UpdateResult(TypedDict):
    scanned_at: str
    timezone: Literal["Europe/Istanbul"]
    requested_sources: list[Literal["LMS", "EWI", "UZEM"]]
    source_status: dict[str, dict[str, object]]
    term: str
    completeness: Literal["PARTIAL", "COMPLETE_IN_SCANNED_SCOPES"]
    sections: list[dict[str, object]]
    changes: list[dict[str, object]]
    timeline: list[dict[str, object]]
    conflicts: list[dict[str, object]]
    cancellations: list[dict[str, object]]
    alerts: list[dict[str, object]]
    conflict_coverage: str
    today: list[dict[str, object]]
    errors: dict[str, str]
    private_sections: str
    missing_information: list[str]
    cloud_verification: Literal["PENDING_CONNECTOR_LIST_AND_READBACK"]
    content_trust: str
    response_has_more: bool
    max_items_per_section: int
    summary_counts: dict[str, int]
    summary_limit: int
