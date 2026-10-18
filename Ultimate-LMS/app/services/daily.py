"""Daily read/sync workflow. All acknowledgments and notifications stay local."""

import html
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import PROJECT_ROOT, load_config
from app.drive import cloud
from app.drive.comparator import validate_drive_path
from app.errors import ActionableError
from app.services import university
from app.services.update import ISTANBUL, university_update
from app.storage.state import digest, file_hash, load_state, operation_lock, save_state, serialized
from app.uzem import sync as uzem_sync

STATE_PATH = PROJECT_ROOT / "data" / "daily.json"
REPORTS = PROJECT_ROOT / "data" / "daily-reports"
TRANSIENT = re.compile(
    r"NETWORK|PORTAL_UNAVAILABLE|TIMEOUT|timed out|net::ERR_|connection", re.IGNORECASE
)
AUTH_FAILURE = re.compile(r"LOGIN|SESSION_EXPIRED|CHALLENGE|CAPTCHA|MFA|CREDENTIAL", re.IGNORECASE)


def _now():
    return datetime.now(UTC).isoformat()


def _code(error):
    match = re.search(r"(?:^|: )([A-Z][A-Z0-9_]{3,})(?=:|$)", str(error))
    return match[1] if match else "SCAN_FAILED"


def _text(value):
    value = str(value or "Unknown")
    value = re.sub(
        r"(?i)(password|cookie|authorization|token|secret)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    value = html.escape(" ".join(value.split())[:500])
    return re.sub(r"([\[\]`*_\\])", r"\\\1", value)


def _url(value):
    parsed = urlsplit(str(value or ""))
    if parsed.scheme != "https" or parsed.hostname not in {
        "lms.altinbas.edu.tr",
        "ewi.altinbas.edu.tr",
        "uzem.altinbas.edu.tr",
    }:
        return ""
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query)
        if k.casefold() in {"sid", "odevid", "newsid", "id", "crid", "action", "showpage"}
    ]
    return urlunsplit((parsed.scheme, parsed.hostname, parsed.path, urlencode(query), ""))


def _stable(value):
    if isinstance(value, dict):
        return {
            k: _stable(v)
            for k, v in value.items()
            if k not in {"scanned_at", "checked_at", "last_seen_at", "change_id", "scan_id"}
        }
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def daily_status():
    return load_state(STATE_PATH).get("run", {"status": "Unknown"})


def _scan_with_retry():
    result = university_update(max_items_per_section=500)
    failed = [
        source
        for source in result["requested_sources"]
        if any(
            (key == source or key.startswith(source + ":"))
            and TRANSIENT.search(str(error))
            and not AUTH_FAILURE.search(str(error))
            for key, error in result["errors"].items()
        )
    ]
    if not failed:
        return result
    time.sleep(2)
    retry = university_update(sources=failed, max_items_per_section=500)
    result["sections"] = [s for s in result["sections"] if s["source"] not in failed] + retry[
        "sections"
    ]
    result["errors"] = {
        k: v for k, v in result["errors"].items() if k.split(":")[0] not in failed
    } | retry["errors"]
    result["source_status"].update({s: retry["source_status"][s] for s in failed})
    # Keep first-attempt changes/alerts even if the retry scanner consumed its baseline.
    result["changes"] += retry["changes"]
    result["alerts"] += retry["alerts"]
    result["scanned_at"] = retry["scanned_at"]
    from app.services.update import timeline_and_conflicts

    result["timeline"], result["conflicts"] = timeline_and_conflicts(result["sections"])
    return result


def _sync_files(source_status, errors):
    config = load_config()
    if config.cloud_account != "ff7hpp@gmail.com" or not config.cloud_university_id:
        errors["DRIVE"] = "CLOUD_DESTINATION_UNKNOWN"
        return [], []
    files, rows = [], []
    for source in ("LMS", "UZEM"):
        if source_status[source]["status"] != "Confirmed":
            errors[f"SYNC:{source}"] = "SOURCE_SCAN_INCOMPLETE"
            continue
        try:
            if source == "LMS":
                items, scans = university.prepare_sync(force_refresh=True)
                from app.services.scanner import scan_errors

                if scan_errors(scans):
                    errors["SYNC:LMS"] = "SOURCE_SCAN_INCOMPLETE"
            else:
                items = uzem_sync.prepare_sync(force_refresh=True)
            before = {
                id(item): (
                    item.comparison.status,
                    file_hash(item.comparison.existing) if item.comparison.existing else None,
                )
                for item in items
            }
            items = university.execute_sync(items, source=source, verify_content=True)
            for item in items:
                record = item.to_dict()
                record["title"] = item.comparison.filename
                record["source_url"] = _url(item.row.get("resource_url"))
                old_status, old_hash = before[id(item)]
                current = item.downloaded_to or item.comparison.existing
                record["status"] = (
                    "FAILED"
                    if item.error
                    else (
                        "UPDATED"
                        if old_hash and current and file_hash(current) != old_hash
                        else "NEW"
                        if old_status in {"NEW", "MISSING"} and item.downloaded_to
                        else "UPDATED"
                        if old_status == "UPDATED" and item.downloaded_to
                        else record["status"]
                    )
                )
                if record["status"] == "MISSING":
                    record["status"] = "UNKNOWN"
                if item.error or record["status"] == "UNKNOWN":
                    errors[f"SYNC:{source}:{item.comparison.filename}"] = (
                        _code(item.error) if item.error else "FILE_IDENTITY_UNKNOWN"
                    )
                record["error"] = _code(item.error) if item.error else None
                files.append(record)
                if item.downloaded_to or item.comparison.existing:
                    rows.append(
                        {
                            "row": item.row,
                            "source": source,
                            "path": str(item.downloaded_to or item.comparison.existing),
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - independent transfer sources retain siblings
            errors[f"SYNC:{source}"] = _code(exc)
    # EWI exposes links/metadata, not an observed authenticated binary download route.
    return files, rows


def render_report(result, *, view="all", course_code=None):
    checked_at = datetime.fromisoformat(result["scanned_at"]).astimezone(ISTANBUL)
    lines = [
        "# مركز الجامعة — التحديث اليومي",
        "",
        f"آخر فحص: {checked_at:%Y-%m-%d %H:%M:%S} | Europe/Istanbul",
        f"الحالة: {result['status']} | Drive: {result['cloud_verification']}",
        "",
        "## حالة المصادر",
        "",
    ]
    for source, status in result["source_status"].items():
        lines.append(f"- {source}: {_text(status['status'])}")
    groups = [
        ("ما الجديد", result["changes"]),
        ("الواجبات القادمة", result["assignments"]),
        ("الإعلانات الجديدة", result["announcements"]),
        ("التعارضات المحتملة", result.get("conflicts", [])),
        (
            "الملفات الجديدة أو المتغيرة",
            [item for item in result["files"] if item["status"] != "PRESENT"],
        ),
        (
            "المواعيد القادمة",
            [item for item in result["upcoming"] if item.get("kind") != "assignment_deadline"],
        ),
    ]
    for title, items in groups:
        if view == "assignments" and title != "الواجبات القادمة":
            continue
        visible = [
            item
            for item in items
            if not course_code
            or str(item.get("course_code", "")).casefold() == course_code.casefold()
        ]
        lines += ["", f"## {title} ({len(visible)})", ""]
        for item in visible[:50]:
            label = " | ".join(
                _text(item.get(k)) for k in ("course_code", "title", "date", "time", "status")
            )
            if item.get("remote_id"):
                label += f" | ID {_text(item['remote_id'])}"
            if item.get("date_status"):
                label += f" | {_text(item['date_status'])} / {_text(item.get('freshness'))}"
            url = _url(item.get("source_url"))
            lines.append(f"- {label}" + (f" — [المصدر]({url})" if url else ""))
        if len(visible) > 50:
            lines.append("- عرض أول 50 عنصرًا؛ التفاصيل عبر روابط المصدر.")
        if not visible:
            lines.append("- لم يُرصد عنصر في هذا الفحص؛ المصادر غير المكتملة موضحة أدناه.")
    lines += ["", "## أخطاء وحدود التغطية", ""]
    lines += [f"- {_text(key)}: {_text(value)}" for key, value in result["errors"].items()]
    lines += [
        "- EWI: روابط الملفات تُعرض؛ تنزيلها التلقائي غير مثبت.",
        "- Confirmed: حقل صريح؛ Unknown: غير متاح؛ STALE: فحص سابق.",
        "- الكتابة على mount لا تثبت الرفع؛ يلزم connected Drive list/readback.",
    ]
    if result.get("response_has_more"):
        lines.append("- النتائج معاينة محدودة؛ التغطية الكاملة عبر صفحات المصدر.")
    return "\n".join(lines) + "\n"


def daily_update(*, sync_files=True):
    if type(sync_files) is not bool:
        raise ValueError("SYNC_MODE_INVALID")
    with operation_lock():
        state = load_state(STATE_PATH)
        started = _now()
        state["run"] = {**state.get("run", {}), "last_run": started, "status": "RUNNING"}
        save_state(STATE_PATH, state)
        try:
            update = _scan_with_retry()
            errors = {key: _code(value) for key, value in update["errors"].items()}
            changes, announcements = [], []
            for change in update["changes"]:
                item = change.get("item", change)
                key = digest(_stable(change))
                if key in state["sections"]:
                    continue
                record = {
                    "change_id": key,
                    "source": change.get("source"),
                    "course_code": item.get("course_code") or change.get("course"),
                    "title": _text(item.get("title") or item.get("name")),
                    "status": change.get("status", "Unknown"),
                    "date": item.get("date"),
                    "source_url": _url(change.get("source_url")),
                }
                changes.append(record)
                is_announcement = any(
                    word in str(change.get("section", change.get("type", "")))
                    for word in ("news", "announcement", "notification")
                )
                record["kind"] = "announcement" if is_announcement else "change"
                if is_announcement:
                    announcements.append(record)
                state["sections"][key] = {"last_seen_at": started, "change": record}
            today = datetime.now(ISTANBUL).date().isoformat()
            upcoming = [
                {
                    key: item.get(key)
                    for key in (
                        "course_code",
                        "title",
                        "date",
                        "time",
                        "status",
                        "source_url",
                        "freshness",
                        "date_status",
                        "kind",
                        "remote_id",
                    )
                }
                for item in update["timeline"]
                if not item.get("date") or item["date"] >= today
            ]
            assignments = [item for item in upcoming if item["kind"] == "assignment_deadline"]
            # Failed assignment details must remain visible as Unknown, not disappear.
            known = {(item.get("course_code"), str(item.get("remote_id"))) for item in assignments}
            for section in update["sections"]:
                if section["section"].split(":")[-1] != "assignments":
                    continue
                for wrapped in section["items"]:
                    item = wrapped["data"]
                    if (
                        item.get("detail_error")
                        and (item.get("course_code"), str(item.get("remote_id"))) not in known
                    ):
                        assignments.append(
                            {
                                "course_code": item.get("course_code"),
                                "title": item.get("title"),
                                "remote_id": item.get("remote_id"),
                                "date": None,
                                "time": None,
                                "date_status": "Unknown",
                                "status": "Page scan failed",
                                "source_url": wrapped.get("source_url"),
                                "freshness": wrapped.get("freshness"),
                            }
                        )
            assignments.sort(key=lambda item: (item.get("date") or "9999", item.get("time") or ""))
            files, rows = _sync_files(update["source_status"], errors) if sync_files else ([], [])
            result = {
                "scanned_at": update["scanned_at"],
                "started_at": started,
                "status": "PARTIAL" if errors else "COMPLETE_IN_SCANNED_SCOPES",
                "source_status": update["source_status"],
                "changes": changes,
                "announcements": announcements,
                "assignments": assignments,
                "upcoming": upcoming,
                "conflicts": [
                    {
                        "course_code": conflict.get("items", [{}])[0].get("course_code"),
                        "title": conflict.get("reason"),
                        "status": conflict.get("status"),
                        "source_url": conflict.get("items", [{}])[0].get("source_url"),
                    }
                    for conflict in update.get("conflicts", [])
                ],
                "files": files,
                "errors": errors,
                "cloud_verification": cloud.PENDING,
                "response_has_more": update.get("response_has_more", False),
            }
            notification_keys = [digest(_stable(item)) for item in update["alerts"]]
            if errors:
                notification_keys.append(digest(errors))
            important = bool(
                changes
                or any(key not in state["sections"] for key in notification_keys)
                or any(item["status"] in {"NEW", "UPDATED"} for item in files)
            )
            for key in notification_keys:
                state["sections"][key] = {"last_seen_at": started}
            result["notify"] = important
            REPORTS.mkdir(parents=True, exist_ok=True)
            report = REPORTS / (
                "daily-" + datetime.now(ISTANBUL).strftime("%Y%m%d-%H%M%S-%f") + ".md"
            )
            result["report_path"] = str(report)
            with report.open("x", encoding="utf-8") as stream:
                stream.write(render_report(result))
            state["latest"] = result
            state["verification_rows"] = rows
            state["sections"] = dict(
                sorted(state["sections"].items(), key=lambda pair: pair[1]["last_seen_at"])[-5000:]
            )
            state["run"].update(
                status=result["status"], last_error=errors or None, last_completed=_now()
            )
            if not errors:
                state["run"]["last_success"] = _now()
            save_state(STATE_PATH, state)
            return result
        except BaseException as exc:
            state["run"].update(
                status="CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                last_error=_code(exc),
                last_completed=_now(),
            )
            save_state(STATE_PATH, state)
            raise


def natural_request(request):
    request = request.strip().rstrip("؟?").strip()
    if request == "ما واجباتي القادمة":
        return render_report(daily_update(sync_files=False), view="assignments")
    if request == "حدّث ملفات الجامعة" or request == "حدث ملفات الجامعة":
        return render_report(daily_update(sync_files=True))
    match = re.fullmatch(r"اعرض تغييرات ([A-Za-z][A-Za-z0-9_-]{1,39})", request)
    if match or request == "ما الجديد اليوم":
        result = daily_update(sync_files=False)
        # Scheduled scans must not make today's already reported changes disappear on request.
        today = datetime.now(ISTANBUL).date()
        result["changes"] = [
            entry["change"]
            for entry in load_state(STATE_PATH)["sections"].values()
            if entry.get("change")
            and datetime.fromisoformat(entry["last_seen_at"]).astimezone(ISTANBUL).date() == today
        ]
        result["announcements"] = [
            item for item in result["changes"] if item.get("kind") == "announcement"
        ]
        return render_report(result, course_code=match[1] if match else None)
    raise ActionableError(
        "REQUEST_UNKNOWN: استخدم: ما الجديد اليوم؟ / ما واجباتي القادمة؟ / حدّث ملفات الجامعة / اعرض تغييرات SWE341"
    )


@serialized
def publish_report(account, university_folder_id):
    """Connected host calls only after listing the selected University folder."""
    state = load_state(STATE_PATH)
    result = state.get("latest")
    config = load_config()
    if not result or result["errors"] or not config.drive_root:
        raise ActionableError("REPORT_NOT_READY: complete a successful daily scan first")
    if (
        account != config.cloud_account
        or account != "ff7hpp@gmail.com"
        or university_folder_id != config.cloud_university_id
    ):
        raise ActionableError("CLOUD_ACCOUNT_OR_FOLDER_MISMATCH")
    from pathlib import Path

    for record in state.get("verification_rows", []):
        status = cloud.verification_status(record["row"], Path(record["path"]), config)
        if not status["cloud_verified_at"] or status["cloud_verified_at"] < result["started_at"]:
            raise ActionableError("CLOUD_READBACK_PENDING: verify every synced file for this run")
    local = Path(result["report_path"])
    if local.parent.resolve() != REPORTS.resolve() or local.is_symlink():
        raise ActionableError("REPORT_PATH_INVALID")
    target = config.drive_root / "University" / local.name
    validate_drive_path(target, config.drive_root)
    if not target.parent.is_dir():
        raise ActionableError("DRIVE_UNAVAILABLE")
    if target.exists():
        if file_hash(target) != file_hash(local):
            raise ActionableError("REPORT_TARGET_EXISTS")
    else:
        with target.open("xb") as stream:
            stream.write(local.read_bytes())
    result["drive_report_path"] = str(target)
    save_state(STATE_PATH, state)
    return {"path": str(target), "sha256": file_hash(target), "cloud_verification": cloud.PENDING}


@serialized
def verify_report(readback, evidence):
    from pathlib import Path

    state = load_state(STATE_PATH)
    result = state.get("latest", {})
    if not result.get("drive_report_path"):
        raise ActionableError("REPORT_NOT_PUBLISHED")
    config = load_config()
    if evidence["folder_id"] != config.cloud_university_id:
        raise ActionableError("CLOUD_ACCOUNT_OR_FOLDER_MISMATCH")
    config = replace(config, cloud_course_folders={"REPORT": config.cloud_university_id})
    path = Path(result["drive_report_path"])
    row = {"course_code": "REPORT", "remote_id": path.name, "semester": config.term}
    receipt = cloud.verify_readback(row, path, Path(readback), evidence, config)
    result["cloud_verification"] = "VERIFIED_AT_RECORDED_TIME"
    state["run"]["last_cloud_success"] = _now()
    save_state(STATE_PATH, state)
    return receipt
