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


@dataclass(frozen=True)
class Announcement:
    title: str
    posted_at: str
    url: str
    content: str = ""


@dataclass(frozen=True)
class CalendarEvent:
    date: str
    title: str
    time: str = ""
    location: str = ""


@dataclass(frozen=True)
class CourseSnapshot:
    course: Course
    weekly_hours: dict[str, str]
    resources: list[Resource]
    announcements: list[Announcement]
    exams: list[dict[str, str]]
    calendar_events: list[CalendarEvent]
    calendar_scope: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
