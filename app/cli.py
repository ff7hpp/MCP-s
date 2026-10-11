"""Local command line entry point."""

import argparse
import json
import sys

from playwright.sync_api import Error

from app.config import load_config, save_drive_root
from app.drive.detector import candidate_roots, select_root
from app.lms.browser import LoginError, manual_ewi_login, manual_login, manual_uzem_login
from app.lms.courses import list_courses
from app.services.documents import read_document
from app.services.scanner import scan_all, scan_one
from app.services.university import execute_sync, prepare_sync
from app.storage.database import get_rows


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
    subcommands.add_parser("login", help="Open visible browser for manual LMS sign-in")
    subcommands.add_parser("ewi-login", help="Open visible browser for manual EWI sign-in")
    subcommands.add_parser("uzem-login", help="Open visible browser for manual old UZEM sign-in")
    for command_name in (
        "uzem-courses",
        "uzem-files",
        "uzem-notifications",
        "uzem-calendar",
        "uzem-grades",
        "uzem-scan",
        "uzem-updates",
    ):
        subcommands.add_parser(command_name, help=f"Read {command_name[5:]} from old UZEM")
    subcommands.add_parser("uzem-compare", help="Compare old UZEM files with the University folder")
    uzem_sync_command = subcommands.add_parser(
        "uzem-sync", help="Preview or copy old UZEM files to Drive"
    )
    uzem_sync_command.add_argument("--course-code", help="Optional enrolled course code")
    uzem_sync_command.add_argument("--execute", action="store_true", help="Download eligible files")
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
    sync_command.add_argument("--dry-run", action="store_true", help="Preview without downloading")
    sync_command.add_argument("--json", action="store_true", help="Print structured JSON")
    read_command = subcommands.add_parser("read", help="Extract text from a local course file")
    read_command.add_argument("course_code")
    read_command.add_argument("filename")
    read_command.add_argument("--json", action="store_true", help="Print structured JSON")
    for name in ("announcements", "exams", "calendar"):
        data_command = subcommands.add_parser(name, help=f"Show stored {name}")
        data_command.add_argument("course_code", nargs="?", help="Optional course code")
        data_command.add_argument("--json", action="store_true", help="Print structured JSON")
    args = parser.parse_args(argv)
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
                items = uzem_sync.prepare_sync(getattr(args, "course_code", None))
                if args.command == "uzem-sync" and args.execute:
                    items = uzem_sync.execute_sync(items)
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
            "uzem-files": lambda: uzem.scan_all()["files"],
            "uzem-notifications": uzem.get_notifications,
            "uzem-calendar": uzem.get_calendar,
            "uzem-grades": uzem.get_grades,
            "uzem-scan": uzem.scan_all,
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
        return 0
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
                if result.error:
                    print(f"  ERROR: {result.error}")
                elif result.changes:
                    for change in result.changes:
                        print(f"  {change['status']} {change['type']}: {change['name']}")
                else:
                    print("  No changes")
            print(
                f"SUMMARY: {sum(len(result.changes) for result in results)} changes, "
                f"{sum(result.error is not None for result in results)} errors"
            )
        return int(any(result.error for result in results))
    if args.command == "sync":
        try:
            items, results = prepare_sync(args.course_code)
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
                f"{sum(result.error is not None for result in results)} scan errors",
                flush=True,
            )
        if not args.dry_run:
            execute_sync(items)
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": args.dry_run,
                        "items": [item.to_dict() for item in items],
                        "scan_errors": {
                            result.code: result.error for result in results if result.error
                        },
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
        return int(any(item.error for item in items) or any(result.error for result in results))
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
    if args.command in {"announcements", "exams", "calendar"}:
        table = {"announcements": "announcements", "exams": "exams", "calendar": "calendar_events"}[
            args.command
        ]
        rows = get_rows(table, args.course_code)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                date = row.get("posted_at") or row.get("date") or ""
                title = row.get("title") or "Exam information"
                print(f"{row['course_code']}\t{date}\t{title}")
            if not rows:
                print("No stored items")
        return 0
    try:
        manual_login()
    except LoginError as exc:
        print(f"LOGIN_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
