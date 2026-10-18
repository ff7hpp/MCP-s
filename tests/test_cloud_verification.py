from dataclasses import replace

import pytest

from app.config import Config
from app.drive import cloud
from app.storage.state import load_state
from tests.test_transfer import row


@pytest.fixture
def files(tmp_path, monkeypatch):
    root = tmp_path / "Drive"
    course = root / "University" / "SWE431 Testing"
    course.mkdir(parents=True)
    local = course / "lecture.pdf"
    local.write_bytes(b"%PDF-1.7\nfixture")
    readbacks = tmp_path / "project" / "downloads" / "cloud-readbacks"
    readbacks.mkdir(parents=True)
    proof = readbacks / "readback.pdf"
    proof.write_bytes(local.read_bytes())
    monkeypatch.setattr(cloud, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(cloud, "READBACK_DIRECTORY", readbacks)
    monkeypatch.setattr(cloud, "STATE_PATH", tmp_path / "cloud.json")
    config = Config(
        term="Fall 2026/2027",
        drive_root=root,
        cloud_account="chosen@example.test",
        cloud_university_id="university-id",
        cloud_course_folders={"SWE431": "course-id"},
    )
    evidence = {
        "account": config.cloud_account,
        "listed_file_id": "file-id",
        "listed_name": local.name,
        "listed_size": local.stat().st_size,
        "folder_id": "course-id",
        "ancestor_ids": [],
        "readback_file_id": "file-id",
        "readback_parent_ids": ["course-id"],
    }
    return local, proof, config, evidence


def test_requires_list_identity_raw_readback_and_matching_hash(files):
    local, proof, config, evidence = files
    metadata = row()
    assert cloud.verification_status(metadata, local, config)["cloud_verification"] == cloud.PENDING
    result = cloud.verify_readback(metadata, local, proof, evidence, config)
    assert result["cloud_verification"] == "VERIFIED_AT_RECORDED_TIME"
    assert result["cloud_verified_at"]
    local.write_bytes(b"changed local bytes")
    assert cloud.verification_status(metadata, local, config)["cloud_verification"] == cloud.PENDING


@pytest.mark.parametrize(
    "key,value,error",
    [
        ("account", "other@example.test", "CLOUD_ACCOUNT_OR_FOLDER_MISMATCH"),
        ("readback_file_id", "another-id", "CLOUD_READBACK_IDENTITY_MISMATCH"),
        ("readback_parent_ids", ["outside-folder"], "CLOUD_READBACK_IDENTITY_MISMATCH"),
        ("listed_size", 1, "CLOUD_READBACK_METADATA_MISMATCH"),
    ],
)
def test_wrong_account_identity_or_size_never_verifies(files, key, value, error):
    local, proof, config, evidence = files
    with pytest.raises(RuntimeError, match=error):
        cloud.verify_readback(row(), local, proof, {**evidence, key: value}, config)
    assert not cloud.STATE_PATH.exists()


def test_same_size_changed_readback_and_source_revision_invalidate_proof(files):
    local, proof, config, evidence = files
    proof.write_bytes(b"x" * local.stat().st_size)
    with pytest.raises(RuntimeError, match="CLOUD_READBACK_CONTENT_MISMATCH"):
        cloud.verify_readback(row(), local, proof, evidence, config)
    proof.write_bytes(local.read_bytes())
    cloud.verify_readback(row(), local, proof, evidence, config)
    assert (
        cloud.verification_status({**row(), "remote_id": "new-id"}, local, config)[
            "cloud_verification"
        ]
        == cloud.PENDING
    )
    assert load_state(cloud.STATE_PATH)["sections"]
    assert (
        cloud.verification_status(row(), local, replace(config, cloud_account="different"))[
            "cloud_verification"
        ]
        == cloud.PENDING
    )
