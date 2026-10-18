"""Live session checks without opening private academic sections."""

import sqlite3
from datetime import UTC, datetime

from app.config import EWI_PROFILE_PATH, EWI_URL, LMS_URL, PROJECT_ROOT, UZEM_URL, load_config
from app.errors import ActionableError
from app.lms.auth import is_authenticated
from app.lms.browser import (
    authenticated_context,
    authenticated_uzem_context,
    is_ewi_authenticated,
    is_uzem_authenticated,
)
from app.runtime import runtime_info
from app.storage.state import load_state, save_state, serialized

METRICS_PATH = PROJECT_ROOT / "data" / "operational_health.json"


@serialized
def record_source_metrics(durations, errors, checked_at):
    state = load_state(METRICS_PATH)
    for source, duration in durations.items():
        previous = state["sections"].get(source, {})
        if not isinstance(previous, dict):
            raise ActionableError(
                "LOCAL_METRICS_INVALID: preserve state and recover a checked backup"
            )
        failures = [
            value.split(":")[0][:80]
            for key, value in errors.items()
            if key == source or key.startswith(source + ":")
        ]
        state["sections"][source] = {
            "last_checked_at": checked_at,
            "last_successful_at": previous.get("last_successful_at") if failures else checked_at,
            "last_error_codes": failures,
            "duration_ms": duration,
            "status": "Partial" if failures else "Confirmed",
        }
    state["scanned_at"] = checked_at
    save_state(METRICS_PATH, state)


@serialized
def university_health():
    sessions = {}
    for source, url, context_factory, authenticated in (
        ("LMS", LMS_URL, authenticated_context, is_authenticated),
        ("EWI", EWI_URL, lambda: authenticated_context(EWI_PROFILE_PATH), is_ewi_authenticated),
        ("UZEM", UZEM_URL, authenticated_uzem_context, is_uzem_authenticated),
    ):
        try:
            with context_factory() as context:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                sessions[source] = {
                    "status": "TESTED LIVE" if authenticated(page) else "BLOCKED",
                    "authenticated": authenticated(page),
                    "source_url": url,
                    "error": None
                    if authenticated(page)
                    else "Session expired; visible manual sign-in required",
                }
        except Exception as exc:  # noqa: BLE001 - isolate portal health
            sessions[source] = {
                "status": "BLOCKED",
                "authenticated": False,
                "source_url": url,
                "error": type(exc).__name__ + ": " + str(exc).splitlines()[0][:180],
            }
    config = load_config()
    root = config.drive_root
    try:
        metrics = load_state(METRICS_PATH)["sections"]
    except (RuntimeError, ValueError, OSError):
        metrics = {"status": "LOCAL_METRICS_UNAVAILABLE"}
    from app.storage.database import DEFAULT_DB, connect

    storage = {"bytes": DEFAULT_DB.stat().st_size if DEFAULT_DB.exists() else 0}
    if DEFAULT_DB.exists():
        try:
            with connect(readonly=True) as db:
                storage["schema_version"] = db.execute("PRAGMA user_version").fetchone()[0]
                storage["row_counts"] = {
                    table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "scan_history",
                        "scan_changes",
                        "section_members",
                        "academic_items",
                    )
                }
        except (RuntimeError, ValueError, OSError, sqlite3.Error):
            storage["status"] = "STORAGE_DIAGNOSTICS_UNAVAILABLE"
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "runtime": runtime_info(),
        "configured_term": config.term,
        "sessions": sessions,
        "source_metrics": metrics,
        "storage": storage,
        "session_age": "Unknown; authenticated checks do not establish the server session start time",
        "drive": {
            "mounted_root": str(root) if root else None,
            "mounted_available": bool(root and root.is_dir()),
            "university_available": bool(root and (root / "University").is_dir()),
            "selected_cloud_account": config.cloud_account,
            "university_folder_id": config.cloud_university_id,
            "cloud_status": "NOT_CHECKED: connected Drive must list destination and read back file; mount presence is not cloud health",
        },
    }
