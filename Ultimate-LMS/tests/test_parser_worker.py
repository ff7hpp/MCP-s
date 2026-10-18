import subprocess
import sys

import pytest

from app.config import PROJECT_ROOT
from app.parsers import isolated
from app.services.documents import MAX_BYTES, _read_path


def test_malformed_and_large_document_leave_next_parse_available(tmp_path):
    malformed = tmp_path / "bad.pdf"
    malformed.write_bytes(b"%PDF-not-a-document")
    with pytest.raises(RuntimeError, match="DOCUMENT_PARSE_FAILED"):
        _read_path(malformed, 100)
    large = tmp_path / "large.pdf"
    with large.open("wb") as stream:
        stream.truncate(MAX_BYTES + 1)
    with pytest.raises(ValueError, match="DOCUMENT_TOO_LARGE"):
        _read_path(large, 100)
    valid = tmp_path / "notes.txt"
    valid.write_text("Successful next extraction", encoding="utf-8")
    assert _read_path(valid, 10).text == "Successful"


def test_parser_timeout_terminates_child_then_next_request_works(monkeypatch, tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("safe", encoding="utf-8")
    run = subprocess.run

    def slow_parser(*args, **kwargs):
        kwargs["timeout"] = 0.1
        return run([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(isolated.subprocess, "run", slow_parser)
        with pytest.raises(RuntimeError, match="DOCUMENT_TIMEOUT"):
            isolated.extract_isolated(path, 100)
    assert isolated.extract_isolated(path, 100) == "safe"


def test_worker_memory_limit_is_enforced():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.parsers.worker import _limit_resources; _limit_resources();\ntry:\n x=bytearray(700*1024*1024)\nexcept MemoryError:\n print('MEMORY_BOUNDED')",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=PROJECT_ROOT,
        check=True,
    )
    assert "MEMORY_BOUNDED" in result.stdout
