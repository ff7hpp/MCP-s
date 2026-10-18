import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import PROJECT_ROOT


def test_fresh_stdio_schema_validation_and_actionable_errors():
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "app.mcp.server"],
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            listed = {item.name: item for item in (await session.list_tools()).tools}
            assert {
                "get_assignments",
                "get_lms_notifications",
                "get_course_links",
                "acknowledge_new_items",
            } <= listed.keys()
            assert len(listed) >= 48
            assert all(
                item.input_schema["additionalProperties"] is False for item in listed.values()
            )
            properties = listed["extract_file_text"].input_schema["properties"]
            assert properties["max_chars"]["maximum"] == 250_000
            assert (
                listed["sync_missing_files"].input_schema["properties"]["dry_run"]["default"]
                is True
            )
            calls = [
                ("ewi_list_sections", {"unexpected": True}, "TOOL_ARGUMENT_UNKNOWN"),
                ("ewi_read_section", {"section": "invalid"}, "EWI_SECTION_UNKNOWN"),
                (
                    "extract_file_text",
                    {"course_code": "SWE431", "filename": "a.pdf", "max_chars": 0},
                    "",
                ),
                ("sync_missing_files", {"dry_run": "false"}, ""),
            ]
            for name, arguments, expected in calls:
                result = await session.call_tool(name, arguments)
                assert result.is_error
                message = " ".join(item.text for item in result.content if hasattr(item, "text"))
                assert expected in message
                assert "Traceback" not in message
                assert message != f"Error executing tool {name}"
            assert not (await session.call_tool("ewi_list_sections", {})).is_error

    asyncio.run(check())


def test_stdio_scan_compare_preview_sync_repeat_in_isolated_state(tmp_path):
    bootstrap = r"""
import sys
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import Mock
from app.config import Config
import app.config as settings
from app.mcp import server
from app.storage import state,database
from app.drive import records,sync
from app.services import university,documents
from app.services.scanner import ScanResult
from app.lms.courses import Course
from app.lms.models import CourseSnapshot,Resource,RemoteFile
from tests.test_transfer import row,Response
root=Path(sys.argv[1]); (root/'University/SWE431 Fixture').mkdir(parents=True)
state.LOCK_PATH=root/'operation.lock';records.STATE_PATH=root/'receipts.json'
config=Config(term="Fall 2026/2027", drive_root=root);settings.load_config=server.load_config=university.load_config=documents.load_config=lambda:config
metadata=row(); db=root/'state.sqlite'
course=Course('SWE431','Fixture','https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=1',config.term)
remote=RemoteFile(metadata['name'],metadata['size'],metadata['created_at'],metadata['download_url'],metadata['remote_id'])
snapshot=CourseSnapshot(course,{},[Resource('Lectures','Fixture','date',1,metadata['resource_url'],files=[remote])],[],[],[],'Explicit empty fixture')
def scan(code):
 return ScanResult(code,snapshot,database.save_snapshot(snapshot,db))
server.scan_one=university.scan_one=scan
server.latest_files=university.latest_files=lambda:database.latest_files(db)
server.stored_section=lambda table,code=None:database.stored_section(table,code,db)
@contextmanager
def context(**kwargs):
 c=Mock();c.pages=[];c.cookies.return_value=[];yield c
university.authenticated_context=context;university.is_authenticated=lambda page:True
sync.DOWNLOADS=root/'downloads'
def opener(*args):
 o=Mock();o.open.return_value=Response(b'%PDF-1.7\n'+b'x'*1015);return o
sync.build_opener=opener
server.mcp.run(transport='stdio')
"""

    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-c", bootstrap, str(tmp_path)],
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.is_error, result.content
                return result.structured_content

            await call("scan_course", {"course_code": "SWE431"})
            compared = await call("compare_with_drive", {"course_code": "SWE431"})
            assert compared["result"][0]["status"] == "MISSING"
            preview = await call("sync_missing_files", {"course_code": "SWE431"})
            assert preview["dry_run"] and not list((tmp_path / "University").rglob("*.pdf"))
            installed = await call(
                "sync_missing_files", {"course_code": "SWE431", "dry_run": False}
            )
            assert installed["items"][0]["status"] == "PRESENT"
            assert (
                installed["items"][0]["cloud_verification"] == "PENDING_CONNECTOR_LIST_AND_READBACK"
            )
            located = await call(
                "get_local_file", {"course_code": "SWE431", "filename": "lecture.pdf"}
            )
            assert located["path"] == installed["items"][0]["downloaded_to"]
            repeat = await call("sync_missing_files", {"course_code": "SWE431", "dry_run": False})
            assert repeat["items"][0]["downloaded_to"] is None
            assert len(list((tmp_path / "University").rglob("*.pdf"))) == 1
            stored = await call("get_course_files", {"course_code": "SWE431"})
            assert (
                len(stored["items"]) == 1 and stored["sections"][0]["freshness"] == "FRESH_AT_SCAN"
            )

    asyncio.run(check())
