"""
End-to-end plan for an incoming CS General Track freshman, built from
sample_data (majors/CMSC.json, gen_eds/UMD.json). `pytest -s` prints the schedule.
"""

from pathlib import Path

import pytest

from optimizer.core import rules
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(scope="module")
def plan():
    loader = DataLoader(SAMPLE_DATA)
    catalog = loader.load_catalog()
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="CS General Track", primary_major="CMSC"),
        primary_major=loader.load_major("CMSC"),
        gen_ed_requirements=loader.load_gen_eds(),
    )
    optimizer = ScheduleOptimizer(catalog)
    schedule = optimizer.optimize_schedule(program)
    for semester in schedule.semesters:
        print(f"{semester}: {' '.join(semester.courses)}")
    return catalog, optimizer, program, schedule


def test_every_requirement_met_except_the_empty_concentration(plan):
    _, optimizer, program, schedule = plan

    report = optimizer.audit(program, schedule)

    assert [r.requirement.id for r in report.unmet] == ["upper_level_concentration"]
    assert report["upper_level_concentration"].reason.startswith("lists no courses")
    assert len(report.results) == len(program.get_all_requirements())


def test_prerequisites_come_in_earlier_semesters(plan):
    schedule = plan[-1]
    term = {code: i for i, semester in enumerate(schedule.semesters) for code in semester.courses}

    for before, after in [("CMSC131", "CMSC132"), ("CMSC132", "CMSC216"), ("CMSC131", "CMSC250"),
                          ("MATH140", "MATH141"), ("MATH141", "MATH240"), ("MATH141", "STAT400")]:
        assert term[before] < term[after], f"{before} must precede {after}"


def test_fits_in_eight_semesters_within_the_upper_level_cmsc_cap(plan):
    catalog, *_, schedule = plan

    assert len(schedule.semesters) <= 8
    for semester in schedule.semesters:
        capped = [c for c in semester.courses if rules.counts_toward_upper_level_cmsc_cap(catalog[c])]
        assert len(capped) <= rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER, f"{semester}: {capped}"
