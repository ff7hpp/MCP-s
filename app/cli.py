"""Local command line entry point."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import Error

from app.config import PROJECT_ROOT, load_config, save_drive_root
from app.drive.detector import candidate_roots, select_root
from app.lms.browser import LoginError, manual_ewi_login, manual_login, manual_uzem_login
from app.lms.courses import list_courses
from app.lms.credentials import configure_credentials, remove_credentials
from app.services.documents import inspect_syllabus, read_document, search_materials
from app.services.scanner import scan_all, scan_errors, scan_one
from app.services.university import execute_sync, prepare_sync
from app.storage.database import recover_database, stored_section
from app.storage.state import recover_state


def configure_drive() -> int:
    current = load_config().drive_root
    if current and current.is_dir():
        print(f"Google Drive root: {current}")
        return 0
    candidates = candidate_roots()
    if len(candidates) == 1:
        selected = candidates[0]
    else:
        if candidates:
            print("Possible Google Drive folders:")
            for index, candidate in enumerate(candidates, 1):
                print(f"{index}. {candidate}")
            response = input("Choose number or enter existing Google Drive folder path: ")
        else:
            response = input("Drive mount not found. Enter Google Drive folder path: ")
        try:
            selected = select_root(candidates, response)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if selected is None:
        print("No Google Drive root selected", file=sys.stderr)
        return 2
    save_drive_root(selected)
    print(f"Google Drive root saved: {selected}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Altinbas LMS local assistant")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("configure-drive", help="Select local Google Drive root")
    backup_command = subcommands.add_parser(
        "backup-state",
        help="Create a private verified state archive; Windows vault credentials are excluded",
    )
    backup_command.add_argument(
        "--profiles",
        action="store_true",
        help="Include closed dedicated browser profiles; archive remains sensitive",
    )
    restore_command = subcommands.add_parser(
        "restore-check",
        help="Restore an archive into a new ignored recovery directory; never overwrite live state",
    )
    restore_command.add_argument("archive")
    term_command = subcommands.add_parser(
        "configure-term",
        help="Select an explicit term, or discover the current enrolled LMS semester",
    )
    term_command.add_argument("term", nargs="?")
    subcommands.add_parser("login", help="Open visible browser for manual LMS sign-in")
    subcommands.add_parser("ewi-login", help="Open visible browser for manual EWI sign-in")
    subcommands.add_parser("uzem-login", help="Open visible browser for manual old UZEM sign-in")
    subcommands.add_parser(
        "auto-login-setup", help="Save newly rotated credentials in Windows Credential Manager"
    )
    subcommands.add_parser("auto-login-remove", help="Remove stored auto-login credentials")
    update_command = subcommands.add_parser(
        "university-update", help="Combined read-only academic update"
    )
    update_command.add_argument("--include-private", action="store_true")
    update_command.add_argument(
        "--sources", nargs="+", choices=["LMS", "EWI", "UZEM"], help="Read only selected portals"
    )
    subcommands.add_parser("university-health", help="Actively test sessions and mounted Drive")
    search_command = subcommands.add_parser(
        "search", help="Search current local course material text"
    )
    search_command.add_argument("course_code")
    search_command.add_argument("query")
    syllabus_command = subcommands.add_parser(
        "syllabus", help="Track syllabus changes and quote explicit evidence"
    )
    syllabus_command.add_argument("course_code")
    syllabus_command.add_argument("filename", nargs="?", default="syllabus.pdf")
    recovery_command = subcommands.add_parser(
        "recover-state", help="Restore a checked backup while preserving original state"
    )
    recovery_command.add_argument(
        "state",
        choices=[
            "state.sqlite",
            "ewi_updates.json",
            "uzem_updates.json",
            "sync_records.json",
            "syllabus_state.json",
            "university_alerts.json",
        ],
    )
    recovery_command.add_argument("backup", help="Filename inside data/backups")
    for command_name in (
        "uzem-courses",
        "uzem-files",
        "uzem-notifications",
        "uzem-calendar",
        "uzem-grades",
        "uzem-scan",
        "uzem-updates",
    ):
        uzem_command = subcommands.add_parser(
            command_name, help=f"Read {command_name[5:]} from old UZEM"
        )
        if command_name == "uzem-scan":
            uzem_command.add_argument("--include-private", action="store_true")
    subcommands.add_parser("uzem-compare", help="Compare old UZEM files with the University folder")
    uzem_sync_command = subcommands.add_parser(
        "uzem-sync", help="Preview or copy old UZEM files to Drive"
    )
    uzem_sync_command.add_argument("--course-code", help="Optional enrolled course code")
    uzem_sync_command.add_argument("--execute", action="store_true", help="Download eligible files")
    uzem_sync_command.add_argument(
        "--verify-content",
        action="store_true",
        help="Recheck remote hashes and adopt identical existing files",
    )
    ewi_courses_command = subcommands.add_parser("ewi-courses", help="Discover courses in EWI")
    ewi_courses_command.add_argument("--json", action="store_true")
    for command_name in (
        "ewi-schedule",
        "ewi-exams",
        "ewi-absences",
        "ewi-resources",
        "ewi-notifications",
        "ewi-news",
    ):
        ewi_command = subcommands.add_parser(command_name, help=f"Read {command_name[4:]} from EWI")
        ewi_command.add_argument("--json", action="store_true")
    course_command = subcommands.add_parser("courses", help="Discover current LMS courses")
    course_command.add_argument("--json", action="store_true", help="Print structured JSON")
    scan_command = subcommands.add_parser("scan", help="Read course metadata without downloading")
    scan_command.add_argument("course_code", help="Code from `courses`")
    scan_command.add_argument("--json", action="store_true", help="Print structured JSON")
    all_command = subcommands.add_parser("scan-all", help="Scan all courses sequentially")
    all_command.add_argument("--json", action="store_true", help="Print structured JSON")
    sync_command = subcommands.add_parser(
        "sync", help="Compare with Drive and safely download missing files"
    )
    sync_command.add_argument("course_code", nargs="?", help="Optional course code")
    sync_mode = sync_command.add_mutually_exclusive_group()
    sync_mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Preview without downloading (default)",
    )
    sync_mode.add_argument(
        "--execute", dest="dry_run", action="store_false", help="Explicitly download eligible files"
    )
    sync_command.add_argument(
        "--verify-content",
        action="store_true",
        help="Recheck remote hashes, including unchanged metadata",
    )
    sync_command.add_argument("--json", action="store_true", help="Print structured JSON")
    read_command = subcommands.add_parser("read", help="Extract text from a local course file")
    read_command.add_argument("course_code")
    read_command.add_argument("filename")
    read_command.add_argument("--json", action="store_true", help="Print structured JSON")
    for name in ("announcements", "exams", "calendar", "assignments", "notifications"):
        data_command = subcommands.add_parser(name, help=f"Show stored {name}")
        data_command.add_argument("course_code", nargs="?", help="Optional course code")
        data_command.add_argument("--json", action="store_true", help="Print structured JSON")
    args = parser.parse_args(argv)
    if args.command in {"backup-state", "restore-check"}:
        from datetime import UTC, datetime

        from app.storage.backup import create_backup, restore_to_new_directory

        try:
            result = (
                create_backup(include_profiles=args.profiles)
                if args.command == "backup-state"
                else restore_to_new_directory(
                    Path(args.archive),
                    PROJECT_ROOT
                    / "data"
                    / "recovery"
                    / datetime.now(UTC).strftime("restore-%Y%m%dT%H%M%S%f"),
                )
            )
        except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"PRIVATE_RECOVERY_ARTIFACT: {result}")
        return 0
    if args.command == "configure-term":
        from dataclasses import replace

        from app.config import load_config, normalized_term, save_config

        try:
            term = args.term
            if term is None:
                terms = {course.semester for course in list_courses()}
                if len(terms) != 1:
                    raise ValueError("ACTIVE_TERM_AMBIGUOUS: select an explicit academic term")
                term = terms.pop()
            if normalized_term(term) is None:
                raise ValueError("ACTIVE_TERM_UNKNOWN: explicit season and year range required")
            save_config(replace(load_config(), term=term))
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"ACTIVE_TERM: {term}")
        return 0
    if args.command in {"auto-login-setup", "auto-login-remove"}:
        try:
            if args.command == "auto-login-setup":
                configure_credentials()
                print("AUTO_LOGIN_READY: credentials saved in Windows Credential Manager")
            else:
                remove_credentials()
                print("AUTO_LOGIN_REMOVED")
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"AUTO_LOGIN_ERROR: {type(exc).__name__}", file=sys.stderr)
            return 1
        return 0
    if args.command == "recover-state":
        if Path(args.backup).name != args.backup:
            print("BACKUP_NAME_INVALID", file=sys.stderr)
            return 2
        path = PROJECT_ROOT / "data" / args.state
        backup = path.parent / "backups" / args.backup
        try:
            recover_database(path, backup) if args.state.endswith(".sqlite") else recover_state(
                path, backup
            )
        except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("STATE_RECOVERED: original preserved in data/backups")
        return 0
    if args.command in {"search", "syllabus"}:
        try:
            result = (
                search_materials(args.course_code, args.query)
                if args.command == "search"
                else inspect_syllabus(args.course_code, args.filename)
            )
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command in {"university-update", "university-health"}:
        from app.services.health import university_health
        from app.services.update import university_update

        try:
            result = (
                university_update(include_private=args.include_private, sources=args.sources)
                if args.command == "university-update"
                else university_health()
            )
        except (RuntimeError, ValueError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "university-health":
            return int(
                not result["drive"]["mounted_available"]
                or any(not session["authenticated"] for session in result["sessions"].values())
            )
        return int(bool(result.get("errors")))
    if args.command == "ewi-login":
        try:
            manual_ewi_login()
        except LoginError as exc:
            print(f"LOGIN_FAILED: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "uzem-login":
        try:
            manual_uzem_login()
        except LoginError as exc:
            print(f"LOGIN_FAILED: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command.startswith("uzem-"):
        from app.uzem import portal as uzem
        from app.uzem import sync as uzem_sync
        from app.uzem.updates import scan_updates as uzem_scan_updates

        if args.command in {"uzem-compare", "uzem-sync"}:
            try:
                items = uzem_sync.prepare_sync(
                    getattr(args, "course_code", None),
                    force_refresh=args.command == "uzem-sync" and args.execute,
                )
                if args.command == "uzem-sync" and args.execute:
                    items = uzem_sync.execute_sync(items, verify_content=args.verify_content)
            except (LoginError, RuntimeError, ValueError, Error) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(
                json.dumps(
                    {
                        "dry_run": args.command == "uzem-compare" or not args.execute,
                        "items": [item.to_dict() for item in items],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return int(any(item.error for item in items))

        readers = {
            "uzem-courses": uzem.list_courses,
            "uzem-files": lambda: uzem.scan_all(include_grades=False)["files"],
            "uzem-notifications": uzem.get_notifications,
            "uzem-calendar": uzem.get_calendar,
            "uzem-grades": uzem.get_grades,
            "uzem-scan": lambda: uzem.scan_all(include_grades=args.include_private),
            "uzem-updates": uzem_scan_updates,
        }
        try:
            result = readers[args.command]()
        except (LoginError, RuntimeError, ValueError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command.startswith("ewi-"):
        from app.ewi import portal as ewi

        readers = {
            "ewi-courses": ewi.list_courses,
            "ewi-schedule": ewi.get_schedule,
            "ewi-exams": ewi.get_exam_results,
            "ewi-absences": ewi.get_absences,
            "ewi-resources": ewi.get_course_resources,
            "ewi-notifications": ewi.get_notifications,
            "ewi-news": ewi.get_news,
        }
        try:
            result = readers[args.command]()
        except (LoginError, RuntimeError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for row in result:
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.command == "configure-drive":
        return configure_drive()
    if args.command == "courses":
        try:
            courses = list_courses()
        except (LoginError, RuntimeError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps([course.to_dict() for course in courses], ensure_ascii=False, indent=2)
            )
        else:
            for course in courses:
                print(f"{course.course_code}\t{course.course_name}")
        return 0
    if args.command == "scan":
        try:
            result = scan_one(args.course_code)
        except (LoginError, RuntimeError, ValueError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        snapshot = result.snapshot
        assert snapshot is not None
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            file_count = sum(len(resource.files) for resource in snapshot.resources)
            print(
                f"{snapshot.course.course_code}: {len(snapshot.resources)} resources, {file_count} files"
            )
            print(f"{len(snapshot.announcements)} announcements, {len(snapshot.exams)} exams")
            print(f"{len(snapshot.calendar_events)} calendar events in {snapshot.calendar_scope}")
            for change in result.changes:
                print(f"{change['status']} {change['type']}: {change['name']}")
            for scope, error in result.errors.items():
                print(f"ERROR {scope}: {error}")
        return int(bool(result.errors))
    if args.command == "scan-all":
        try:
            results = scan_all()
        except (LoginError, RuntimeError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2)
            )
        else:
            for result in results:
                print(result.code)
                for scope, error in result.errors.items():
                    print(f"  ERROR {scope}: {error}")
                if result.changes:
                    for change in result.changes:
                        print(f"  {change['status']} {change['type']}: {change['name']}")
                elif not result.errors:
                    print("  No changes")
            print(
                f"SUMMARY: {sum(len(result.changes) for result in results)} changes, "
                f"{len(scan_errors(results))} errors"
            )
        return int(bool(scan_errors(results)))
    if args.command == "sync":
        try:
            items, results = prepare_sync(args.course_code, force_refresh=not args.dry_run)
        except (LoginError, RuntimeError, ValueError, Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        eligible = [
            item for item in items if item.comparison.status in {"MISSING", "NEW", "UPDATED"}
        ]
        if not args.json:
            for item in items:
                comp = item.comparison
                print(f"{comp.course_code}: {comp.status} {comp.filename}")
                if comp.status in {"MISSING", "NEW", "UPDATED"}:
                    print(f"  {'Would download' if args.dry_run else 'Download'} to {comp.target}")
                elif comp.reason:
                    print(f"  {comp.reason}")
            print(
                f"SUMMARY: {len(eligible)} downloads planned, "
                f"{len(scan_errors(results))} scan errors",
                flush=True,
            )
        if not args.dry_run:
            execute_sync(items, verify_content=args.verify_content)
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": args.dry_run,
                        "items": [item.to_dict() for item in items],
                        "scan_errors": scan_errors(results),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif not args.dry_run:
            for item in items:
                if item.downloaded_to:
                    print(f"SAVED: {item.downloaded_to}")
                elif item.error:
                    print(f"DOWNLOAD_FAILED: {item.comparison.filename}: {item.error}")
        return int(any(item.error for item in items) or bool(scan_errors(results)))
    if args.command == "read":
        try:
            document = read_document(args.course_code, args.filename)
        except (ValueError, FileNotFoundError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(document.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"FILE: {document.path}")
            print(f"SIZE: {document.size_bytes} bytes")
            print(document.text)
            if document.truncated:
                print(f"[TRUNCATED at {len(document.text)} characters]")
        return 0
    if args.command in {"announcements", "exams", "calendar", "assignments", "notifications"}:
        table = "calendar_events" if args.command == "calendar" else args.command
        result = stored_section(table, args.course_code)
        rows = result["items"]
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                date = row.get("due_at") or row.get("posted_at") or row.get("date") or "Unknown"
                title = row.get("title") or "Exam information"
                identity = f" [{row['remote_id']}]" if row.get("remote_id") else ""
                print(f"{row['course_code']}{identity}\t{date}\t{title}")
                if table == "assignments":
                    print(
                        f"  Submission: {row.get('submission_status') or 'Unknown'}; {row.get('detail_error') or 'detail verified at ' + str(row.get('checked_at'))}"
                    )
            if not rows:
                print("No stored items")
            for status in result["sections"]:
                print(
                    f"CACHE: {status['course_code']} {status['freshness']} as of {status['last_successful_at']}"
                )
            for error in result["errors"]:
                print(f"WARNING: {error}")
        return 0
    try:
        manual_login()
    except LoginError as exc:
        print(f"LOGIN_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
