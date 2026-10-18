"""Term-scoped sync receipts. A local receipt never confirms cloud placement."""

from datetime import UTC, datetime
from pathlib import Path

from app.config import PROJECT_ROOT, Config, normalized_term
from app.storage.state import (
    digest,
    file_hash,
    load_state,
    save_state,
    serialized,
    validate_sync_record,
)

STATE_PATH = PROJECT_ROOT / "data" / "sync_records.json"


def identity(row: dict, config: Config, source: str) -> str:
    return digest([source, config.term, row["course_code"], row["resource_url"], row["name"]])


def revision(row: dict) -> str:
    return digest(
        {
            "source_term": normalized_term(row.get("semester")),
            **{
                key: row.get(key)
                for key in (
                    "revision",
                    "remote_id",
                    "created_at",
                    "size",
                    "download_url",
                    "etag",
                    "last_modified",
                )
            },
        }
    )


def get_record(key: str) -> dict | None:
    record = load_state(STATE_PATH)["sections"].get(key)
    if record is not None:
        validate_sync_record(record)
    return record


@serialized
def _record(
    key: str,
    remote_revision: str,
    path: Path,
    content: Path,
    status: str,
    staged: Path | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    state = load_state(STATE_PATH)
    state["sections"][key] = {
        **(metadata or {}),
        "revision": remote_revision,
        "path": str(path.resolve()),
        "sha256": file_hash(content),
        "size": content.stat().st_size,
        "status": status,
        "staged": str(staged) if staged else None,
        "synced_at": datetime.now(UTC).isoformat(),
        "cloud_verified": False,
    }
    save_state(STATE_PATH, state)


def record_install(
    key: str, remote_revision: str, path: Path, *, metadata: dict[str, str] | None = None
) -> None:
    _record(key, remote_revision, path, path, "installed", metadata=metadata)


def record_pending(
    key: str,
    remote_revision: str,
    path: Path,
    content: Path,
    staged: Path | None = None,
    *,
    metadata: dict[str, str] | None = None,
) -> None:
    _record(key, remote_revision, path, content, "pending", staged, metadata)
