from io import BytesIO
from typing import ClassVar
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from app.config import Config
from app.drive import sync
from app.drive.comparator import compare_file
from app.storage.state import file_hash


def row():
    resource = "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersKaynaklari?Action=Details&SID=1&CRID=2"
    return {
        "course_code": "SWE431",
        "semester": "Fall 2026/2027",
        "name": "lecture.pdf",
        "size": "1024 B",
        "revision": 1,
        "remote_id": "3",
        "created_at": "15.10.2026",
        "resource_title": "Lectures",
        "resource_url": resource,
        "download_url": resource + "&DownloadFile=3",
    }


class Response(BytesIO):
    status = 200
    headers: ClassVar[dict] = {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="lecture.pdf"',
    }


@pytest.fixture
def transfer_setup(tmp_path, monkeypatch):
    config = Config(term="Fall 2026/2027", drive_root=tmp_path)
    course = tmp_path / "University" / "SWE431 Testing"
    course.mkdir(parents=True)
    monkeypatch.setattr("app.config.load_config", lambda: config)
    monkeypatch.setattr(sync, "DOWNLOADS", tmp_path / "downloads")
    context = Mock()
    context.cookies.return_value = []
    return config, course, context


def test_verify_adopts_existing_without_duplicate(transfer_setup, monkeypatch):
    config, course, context = transfer_setup
    data = b"%PDF-1.7\n" + b"x" * 1015
    existing = course / "lecture.pdf"
    existing.write_bytes(data)
    opener = Mock()
    opener.open.return_value = Response(data)
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    assert compare_file(row(), config).status == "UNKNOWN"
    installed = sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert installed == existing
    assert len(list(course.rglob("*.pdf"))) == 1
    assert compare_file(row(), config).status == "PRESENT"


def test_same_metadata_replacement_detected_by_explicit_content_verification(
    transfer_setup, monkeypatch
):
    config, course, context = transfer_setup
    original = course / "lecture.pdf"
    original.write_bytes(b"%PDF-1.7\n" + b"x" * 1015)
    opener = Mock()
    opener.open.side_effect = [
        Response(original.read_bytes()),
        Response(b"%PDF-1.7\n" + b"y" * 1015),
    ]
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    old_hash = file_hash(original)
    replacement = sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert replacement != original
    assert file_hash(original) == old_hash
    assert file_hash(replacement) != old_hash
    assert compare_file(row(), config).existing == replacement


def test_external_redirect_rejected_before_credentials_or_request(transfer_setup, monkeypatch):
    config, _, context = transfer_setup
    opener = Mock()
    opener.open.side_effect = HTTPError(
        row()["download_url"], 302, "Redirect", {"Location": "https://evil.test/file.pdf"}, None
    )
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    with pytest.raises(ValueError, match="REDIRECT_REJECTED"):
        sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert opener.open.call_count == 1
    assert context.cookies.call_count == 1


def test_chunked_oversize_rejected_without_install(transfer_setup, monkeypatch):
    config, course, context = transfer_setup
    monkeypatch.setattr(sync, "MAX_BYTES", 100)
    opener = Mock()
    opener.open.return_value = Response(b"%PDF-1.7\n" + b"x" * 1024)
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    with pytest.raises(ValueError, match="TOO_LARGE"):
        sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert not list(course.rglob("*.pdf"))


def test_verified_legacy_file_relocated_without_extra_copy(transfer_setup, monkeypatch):
    config, course, context = transfer_setup
    legacy = config.drive_root / "University" / "Fall 2026-2027" / "SWE431" / "lecture.pdf"
    legacy.parent.mkdir(parents=True)
    data = b"%PDF-1.7\n" + b"x" * 1015
    legacy.write_bytes(data)
    opener = Mock()
    opener.open.return_value = Response(data)
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    result = sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert result.is_relative_to(course)
    assert not legacy.exists()
    assert len(list((config.drive_root / "University").rglob("*.pdf"))) == 1


def test_pending_receipt_survives_failed_atomic_rename(transfer_setup, monkeypatch):
    config, _, _ = transfer_setup
    incoming = config.drive_root / "incoming"
    incoming.write_bytes(b"x" * 1024)
    with monkeypatch.context() as patch:
        patch.setattr(sync.os, "rename", Mock(side_effect=OSError("Interrupted rename")))
        with pytest.raises(OSError):
            sync.install_download(incoming, compare_file(row(), config), row()["size"])
    assert compare_file(row(), config).status == "UPDATED"
    sync.install_download(incoming, compare_file(row(), config), row()["size"])
    assert compare_file(row(), config).status == "PRESENT"


def test_bounded_retry_of_transient_get_failure(transfer_setup, monkeypatch):
    config, _, context = transfer_setup
    opener = Mock()
    opener.open.side_effect = [
        URLError("Temporary network failure"),
        Response(b"%PDF-1.7\n" + b"x" * 1015),
    ]
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    monkeypatch.setattr(sync.time, "sleep", lambda delay: None)
    sync.transfer_file(context, row(), compare_file(row(), config), source="LMS")
    assert opener.open.call_count == 2
    assert compare_file(row(), config).status == "PRESENT"


def test_resume_cleans_only_journal_owned_staging_file(transfer_setup):
    from app.drive.records import record_pending

    config, _, _ = transfer_setup
    incoming = config.drive_root / "incoming"
    incoming.write_bytes(b"x" * 1024)
    comparison = compare_file(row(), config)
    target = sync._destination(comparison)
    target.parent.mkdir(parents=True)
    staged = target.parent / f".lms-{comparison.sync_key[:12]}-interrupted.part"
    staged.write_bytes(b"partial")
    unrelated = target.parent / ".lms-user-work.part"
    unrelated.write_bytes(b"preserve")
    record_pending(comparison.sync_key, comparison.remote_revision, target, incoming, staged)
    sync.install_download(incoming, compare_file(row(), config), row()["size"])
    assert not staged.exists()
    assert unrelated.read_bytes() == b"preserve"


def test_staging_bit_corruption_is_not_installed(transfer_setup, monkeypatch):
    config, course, _ = transfer_setup
    incoming = config.drive_root / "incoming"
    incoming.write_bytes(b"x" * 1024)
    monkeypatch.setattr(
        sync.shutil, "copyfileobj", lambda source, target: target.write(b"z" * 1024)
    )
    with pytest.raises(ValueError, match="integrity differs"):
        sync.install_download(incoming, compare_file(row(), config), row()["size"])
    assert not list(course.rglob("*.pdf"))


def test_total_transfer_deadline_prevents_install(transfer_setup, monkeypatch):
    config, course, context = transfer_setup
    comparison = compare_file(row(), config)
    clock = [0]

    class SlowResponse(Response):
        def read(self, size=-1):
            clock[0] = 121
            return super().read(size)

    opener = Mock()
    opener.open.return_value = SlowResponse(b"%PDF-1.7\n" + b"x" * 1015)
    monkeypatch.setattr(sync, "build_opener", lambda _: opener)
    monkeypatch.setattr(sync.time, "monotonic", lambda: clock[0])
    with pytest.raises(ValueError, match="DOWNLOAD_DEADLINE_EXCEEDED"):
        sync.transfer_file(context, row(), comparison, source="LMS")
    assert not list(course.rglob("*.pdf"))
