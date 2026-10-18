"""Fresh stdio smoke/live checks. Private responses stay in ignored data/."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="*", default=["university_health", "university_update"])
    parser.add_argument("--course-code")
    parser.add_argument(
        "--execute", action="store_true", help="Execute authorized course-file sync"
    )
    parser.add_argument("--verify-content", action="store_true")
    parser.add_argument("--query", default="testing")
    parser.add_argument("--filename", default="syllabus.pdf")
    args = parser.parse_args()
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp.server"], env=environment, cwd=str(ROOT)
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        tools = {tool.name: tool for tool in listed.tools}
        assert {
            "university_update",
            "university_health",
            "sync_missing_files",
            "daily_update",
            "university_request",
            "daily_status",
            "publish_daily_report",
            "verify_daily_report",
        } <= tools.keys()
        assert tools["sync_missing_files"].input_schema["properties"]["dry_run"]["default"] is True
        assert tools["daily_update"].input_schema["properties"]["sync_files"]["default"] is False
        print("STDIO_SCHEMA_OK", len(tools), flush=True)
        for name in args.tools:
            arguments = {}
            if (
                name
                in {
                    "compare_with_drive",
                    "sync_missing_files",
                    "uzem_compare_with_drive",
                    "uzem_sync_missing_files",
                }
                and args.course_code
            ):
                arguments["course_code"] = args.course_code
            if name in {"sync_missing_files", "uzem_sync_missing_files"}:
                arguments.update(dry_run=not args.execute, verify_content=args.verify_content)
            if name == "daily_update":
                arguments["sync_files"] = args.execute
            if name in {"inspect_course_syllabus", "search_course_materials"}:
                arguments["course_code"] = args.course_code or "SWE431"
                if name == "inspect_course_syllabus":
                    arguments["filename"] = args.filename
                else:
                    arguments["query"] = args.query
            result = await session.call_tool(name, arguments)
            if result.is_error:
                print(
                    json.dumps(
                        {"tool": name, "is_error": True, "error": str(result.content[0].text)[:300]}
                    ),
                    flush=True,
                )
                continue
            payload = result.structured_content
            if payload is None:
                payload = json.loads(
                    next(item.text for item in result.content if hasattr(item, "text"))
                )
            if isinstance(payload, list):
                payload = {"items": payload}
            if isinstance(payload.get("result"), list):
                payload = {"items": payload["result"]}
            (ROOT / "data" / f"audit-{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if name == "university_health":
                assert payload["runtime"]["reconnect_required"] is False
                print(
                    json.dumps({"tool": name, "is_error": result.is_error, **payload}), flush=True
                )
            else:
                print(
                    json.dumps(
                        {
                            "tool": name,
                            "is_error": result.is_error,
                            "sections": len(payload.get("sections", [])),
                            "changes": len(payload.get("changes", [])),
                            "errors": payload.get("errors", {}),
                            "scan_errors": payload.get("scan_errors", {}),
                            "file_statuses": [
                                item.get("status") for item in payload.get("items", [])
                            ],
                            "file_errors": [
                                item["error"]
                                for item in payload.get("items", [])
                                if item.get("error")
                            ],
                            "transfers": sum(
                                bool(item.get("downloaded_to")) for item in payload.get("items", [])
                            ),
                            "matches": len(payload.get("matches", [])),
                            "syllabus_status": payload.get("change_status"),
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(main())
