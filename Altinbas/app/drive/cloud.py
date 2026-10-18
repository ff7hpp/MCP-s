"""Connected-host list/readback evidence; a mounted write never verifies Drive."""

from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from app.config import PROJECT_ROOT, load_config
from app.drive.comparator import compare_file, validate_drive_path
from app.drive.records import revision
from app.errors import ActionableError
from app.storage.state import digest, file_hash, load_state, save_state, serialized

STATE_PATH = PROJECT_ROOT / "data" / "cloud_verifications.json"
READBACK_DIRECTORY = PROJECT_ROOT / "downloads" / "cloud-readbacks"
PENDING = "PENDING_CONNECTOR_LIST_AND_READBACK"


class DriveEvidence(TypedDict):
    account: str
    listed_file_id: str
    listed_name: str
    listed_size: int
    folder_id: str
    ancestor_ids: list[str]
    readback_file_id: str
    readback_parent_ids: list[str]


def _key(path, config, row=None):
    validate_drive_path(path, config.drive_root)
    return digest(
        [
            config.cloud_account,
            config.cloud_university_id,
            config.term,
            str(path.resolve()).casefold(),
            *([revision(row)] if row is not None else []),
        ]
    )


def verification_status(row, local_path, config):
    pending = {"cloud_verification": PENDING, "cloud_verified_at": None}
    if not local_path or not config.cloud_account or not config.drive_root:
        return pending
    path = Path(local_path)
    if not path.is_file():
        return pending
    receipts = load_state(STATE_PATH)["sections"]
    # One physical file can satisfy independent LMS and UZEM revisions.
    receipt = receipts.get(_key(path, config, row)) or receipts.get(_key(path, config))
    if receipt is not None and (
        not isinstance(receipt, dict)
        or not all(
            isinstance(receipt.get(name), str)
            for name in ("verified_at", "sha256", "remote_revision", "file_id", "folder_id")
        )
    ):
        raise ActionableError("CLOUD_RECEIPT_INVALID: preserve state and recover a checked backup")
    if (
        not isinstance(receipt, dict)
        or receipt.get("remote_revision") != revision(row)
        or receipt.get("sha256") != file_hash(path)
    ):
        return pending
    return {
        "cloud_verification": "VERIFIED_AT_RECORDED_TIME",
        "cloud_verified_at": receipt["verified_at"],
        "cloud_file_id": receipt["file_id"],
        "cloud_folder_id": receipt["folder_id"],
    }


def verification_plan(rows, config=None, *, source="LMS"):
    config = config or load_config()
    if not config.drive_root or not config.cloud_account or not config.cloud_university_id:
        raise ActionableError(
            "CLOUD_DESTINATION_UNKNOWN: bind the intended account and University folder first"
        )
    items = []
    for row in rows:
        comparison = compare_file(row, config, source=source)
        local = comparison.existing
        if local is None or not local.is_file():
            continue
        validate_drive_path(local, config.drive_root)
        status = verification_status(row, local, config)
        items.append(
            {
                "course_code": row["course_code"],
                "source": source,
                "filename": row["name"],
                "local_path": str(local),
                "local_sha256": file_hash(local),
                "size_bytes": local.stat().st_size,
                "course_folder_id": config.cloud_course_folders.get(str(row["course_code"])),
                **status,
            }
        )
    return {
        "account": config.cloud_account,
        "university_folder_id": config.cloud_university_id,
        "items": items,
        "readback_directory": str(READBACK_DIRECTORY),
        "steps": [
            "Use connected Drive with this account; list the exact destination and verify ancestry under the course folder",
            "Fetch the listed file as raw bytes; materialize under readback_directory",
            "Call verify_drive_readback with listing and fetch metadata; checksum must match the local bytes",
        ],
        "boundary": "Standalone stdio cannot call the desktop Drive connector. The connected host supplies provider evidence; no Drive credentials enter this server.",
    }


@serialized
def verify_readback(row, local_path: Path, readback: Path, evidence: DriveEvidence, config=None):
    config = config or load_config()
    folder = config.cloud_course_folders.get(str(row["course_code"]))
    if not config.drive_root or not folder or evidence["account"] != config.cloud_account:
        raise ActionableError("CLOUD_ACCOUNT_OR_FOLDER_MISMATCH")
    if (
        evidence["listed_file_id"] != evidence["readback_file_id"]
        or not evidence["listed_file_id"]
        or evidence["folder_id"] not in evidence["readback_parent_ids"]
        or (folder != evidence["folder_id"] and folder not in evidence["ancestor_ids"])
    ):
        raise ActionableError("CLOUD_READBACK_IDENTITY_MISMATCH")
    validate_drive_path(local_path, config.drive_root)
    if (
        not readback.resolve().is_relative_to(READBACK_DIRECTORY.resolve())
        or readback.is_symlink()
        or readback.is_junction()
    ):
        raise ActionableError("CLOUD_READBACK_PATH_INVALID")
    current = readback
    while current != PROJECT_ROOT:
        if current.is_symlink() or current.is_junction() or current.parent == current:
            raise ActionableError("CLOUD_READBACK_PATH_INVALID")
        current = current.parent
    if not local_path.is_file() or not readback.is_file():
        raise ActionableError("CLOUD_READBACK_MISSING")
    if (
        type(evidence["listed_size"]) is not int
        or not 0 < evidence["listed_size"] <= 25 * 1024 * 1024
        or evidence["listed_name"] != local_path.name
        or evidence["listed_size"] != local_path.stat().st_size
        or readback.stat().st_size != evidence["listed_size"]
    ):
        raise ActionableError("CLOUD_READBACK_METADATA_MISMATCH")
    local_hash, remote_hash = file_hash(local_path), file_hash(readback)
    if local_hash != remote_hash:
        raise ActionableError("CLOUD_READBACK_CONTENT_MISMATCH")
    state = load_state(STATE_PATH)
    state["sections"][_key(local_path, config, row)] = {
        "verified_at": datetime.now(UTC).isoformat(),
        "account": config.cloud_account,
        "file_id": evidence["listed_file_id"],
        "folder_id": evidence["folder_id"],
        "sha256": local_hash,
        "size": readback.stat().st_size,
        "remote_revision": revision(row),
        "evidence_origin": "Host-supplied connected Drive listing and raw fetch; not an independent server OAuth query",
    }
    save_state(STATE_PATH, state)
    return verification_status(row, local_path, config)
