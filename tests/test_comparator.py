from pathlib import Path

from app.config import Config
from app.drive.comparator import (
    compare_file,
    course_target,
    normalized_name,
    safe_component,
    size_matches,
)


def row() -> dict[str, object]:
    return {
        "course_code": "SWE431",
        "name": "Lecture 1.pdf",
        "size": "1.00 KB",
        "revision": 1,
        "resource_title": "SWE431-Material",
        "resource_url": "https://lms.altinbas.edu.tr/resource?CRID=1119",
    }


def test_normalization_and_size() -> None:
    assert normalized_name("LECTURE_1.PDF") == normalized_name("Lecture 1.pdf")
    assert normalized_name("Lecture 1.docx") != normalized_name("Lecture 1.pdf")
    assert size_matches("1.00 KB", 1024) is True
    assert size_matches("1.00 KB", 500) is False


def test_safe_target(tmp_path: Path) -> None:
    config = Config(drive_root=tmp_path)
    target = course_target(
        config,
        "SWE431",
        "Material",
        "https://lms.altinbas.edu.tr/resource?CRID=2",
        "../Lecture?.pdf",
    )
    assert target.is_relative_to(tmp_path)
    assert target.name == "-Lecture-.pdf"
    assert safe_component("CON") == "_CON"


def test_present_missing_and_unknown(tmp_path: Path) -> None:
    config = Config(drive_root=tmp_path)
    course = tmp_path / "University" / "Other term" / "SWE431 - Software Testing"
    course.mkdir(parents=True)
    assert compare_file(row(), config).status == "MISSING"
    existing = course / "LECTURE_1.PDF"
    existing.write_bytes(b"x" * 1024)
    assert compare_file(row(), config).status == "PRESENT"
    existing.write_bytes(b"x" * 500)
    assert compare_file(row(), config).status == "UNKNOWN"
    assert compare_file({**row(), "revision": 2}, config).status == "UPDATED"
    second = course / "Lecture-1.pdf"
    second.write_bytes(b"x" * 1024)
    assert compare_file(row(), config).status == "UNKNOWN"
