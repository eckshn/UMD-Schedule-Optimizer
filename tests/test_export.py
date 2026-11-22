"""Plan export: Markdown, CSV and iCalendar (optimizer/export.py) and umd-plan plan --format/--output."""

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from optimizer.cli import main
from optimizer.core.audit import AuditReport, RequirementResult
from optimizer.export import to_csv, to_ical, to_markdown
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course
from optimizer.models.requirements import Requirement, RequirementType
from optimizer.models.schedule import Schedule, Semester, SemesterType

ROOT = Path(__file__).resolve().parent.parent
LONG = "A Very Long Course Title, With Commas; Semicolons | Pipes and Ünïcödé Letters Too"
CATALOG = Catalog({
    "AAA100": Course(code="AAA100", name="Intro", credits=3),
    "BBB200": Course(code="BBB200", name=LONG, credits=4),
})


def plan(*semesters):
    schedule = Schedule()
    for year, term, courses in semesters:
        schedule.add_semester(Semester(year=year, type=term, courses=list(courses)))
    return schedule


PLAN = plan((2025, SemesterType.FALL, ["AAA100"]), (2026, SemesterType.WINTER, ["BBB200"]))


def test_markdown_has_a_table_per_semester_and_the_unmet_requirements():
    requirement = Requirement(id="r", name="Needs X", type=RequirementType.COURSE, course_code="X")
    report = AuditReport((RequirementResult(requirement, False, reason="missing X"),))

    text = to_markdown([PLAN, PLAN], CATALOG, "Terp", [report, AuditReport(())], earned=6)

    assert text.startswith("# Terp\n")
    assert "## Plan 1 of 2" in text and "### Fall 2025 (3 credits)" in text
    assert "| AAA100 | Intro | 3 |" in text
    assert "| BBB200 | A Very Long Course Title, With Commas; Semicolons \\| Pipes" in text
    assert "**Total:** 7 credits in 2 terms, plus 6 already earned." in text
    assert "- Needs X: missing X" in text
    assert "All 0 requirements met." in text


def test_csv_has_a_row_per_course():
    rows = list(csv.DictReader(io.StringIO(to_csv([PLAN], CATALOG))))

    assert [(r["plan"], r["term"], r["year"], r["code"], r["credits"]) for r in rows] == [
        ("1", "Fall", "2025", "AAA100", "3"), ("1", "Winter", "2026", "BBB200", "4")]
    assert rows[1]["title"] == LONG


def test_ical_has_an_all_day_event_per_course():
    text = to_ical(PLAN, CATALOG, stamp=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")  # CRLF line endings only
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert unfolded.count("BEGIN:VEVENT") == 2
    assert "UID:AAA100-Fall-2025@umd-schedule-optimizer" in unfolded
    assert "DTSTAMP:20260101T000000Z" in unfolded
    assert "DTSTART;VALUE=DATE:20250831\r\nDTEND;VALUE=DATE:20251220" in unfolded  # end exclusive
    assert "DTSTART;VALUE=DATE:20260102\r\nDTEND;VALUE=DATE:20260123" in unfolded  # Winter 2026
    assert "SUMMARY:BBB200 A Very Long Course Title\\, With Commas\\; Semicolons" in unfolded
    assert "Ünïcödé" in unfolded


def run(capsys, *argv):
    status = main([*argv, "--data-dir", str(ROOT / "sample_data")])
    return status, capsys.readouterr()


def test_plan_writes_the_format_its_output_extension_names(capsys, tmp_path):
    profile = tmp_path / "p.json"
    profile.write_text('{"name": "T", "majors": ["CMSC"]}')

    for name, start in (("plan.md", "# T: "), ("plan.csv", "plan,term,year"),
                        ("plan.ics", "BEGIN:VCALENDAR\r\n"), ("plan.txt", "T: ")):
        status, out = run(capsys, "plan", str(profile), "--no-solver", "-o", str(tmp_path / name))
        assert status == 0 and out.out == ""
        assert (tmp_path / name).read_bytes().decode().startswith(start), name


def test_plan_format_prints_to_stdout(capsys, tmp_path):
    profile = tmp_path / "p.json"
    profile.write_text('{"majors": ["CMSC"]}')

    status, out = run(capsys, "plan", str(profile), "--no-solver", "--format", "csv")

    assert status == 0
    assert out.out.startswith("plan,term,year,code,title,credits\n1,Fall,2025,")


def test_unwritable_output_is_an_error(capsys, tmp_path):
    profile = tmp_path / "p.json"
    profile.write_text('{"majors": ["CMSC"]}')

    status, out = run(capsys, "plan", str(profile), "--no-solver",
                      "-o", str(tmp_path / "missing" / "plan.md"))

    assert status == 2 and "can't write" in out.err
