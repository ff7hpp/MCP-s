from app.lms.courses import parse_course_row


def test_parse_course_row_with_sid() -> None:
    course = parse_course_row(
        ["SWE431", "SOFTWARE TESTING AND VALIDATION", "1", "Instructor", "4.00", "5.00"],
        "window.location='https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=39648';",
        "2026-2027 Educational season Fall Semester",
    )
    assert course.course_code == "SWE431"
    assert course.url == "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/Dersler/DersDetay?SID=39648"
    assert course.ects == "5.00"


def test_parse_course_row_without_sid() -> None:
    course = parse_course_row(["IE208", "ENGINEERING ECONOMICS"], None, "Fall")
    assert course.url is None
    assert course.course_code == "IE208"
