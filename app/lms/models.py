"""Structured LMS metadata. Dates remain as the LMS supplied them."""

from dataclasses import asdict, dataclass, field

from app.lms.courses import Course


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: str
    created_at: str
    download_url: str
    remote_id: str


@dataclass(frozen=True)
class Resource:
    title: str
    uploader: str
    created_at: str
    file_count: int
    url: str
    description: str = ""
    files: list[RemoteFile] = field(default_factory=list)
    detail_error: str | None = None


@dataclass(frozen=True)
class Announcement:
    title: str
    posted_at: str
    url: str
    content: str = ""
    detail_error: str | None = None


@dataclass(frozen=True)
class CalendarEvent:
    date: str
    title: str
    time: str = ""
    location: str = ""
    remote_id: str = ""
    description: str = ""
    source_url: str = ""
    event_type: str = ""
    end_date: str = ""


@dataclass(frozen=True)
class Assignment:
    remote_id: str
    title: str
    url: str
    start_at: str | None = None
    end_at: str | None = None
    effective_due_at: str | None = None
    due_at: str | None = None
    instructions: dict[str, str] = field(default_factory=dict)
    status: str | None = None
    submission_status: str | None = None
    attachments: list[RemoteFile] | None = None
    submitted_files: list[RemoteFile] | None = None
    checked_at: str | None = None
    field_status: dict[str, str] = field(default_factory=dict)
    detail_error: str | None = None


@dataclass(frozen=True)
class CourseSnapshot:
    course: Course
    weekly_hours: dict[str, str]
    resources: list[Resource]
    announcements: list[Announcement]
    exams: list[dict[str, object]]
    calendar_events: list[CalendarEvent]
    calendar_scope: str
    warnings: list[str] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    live_lessons: list[dict] = field(default_factory=list)
    study_links: list[dict] = field(default_factory=list)
    section_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
