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


def test_every_requirement_is_met(plan):
    _, optimizer, program, schedule = plan

    report = optimizer.audit(program, schedule)

    assert [(r.requirement.id, r.reason) for r in report.unmet] == []
    assert 120 <= report["total_credits"].credits <= 125  # free electives fill the gap
    assert len(report.results) == (len(program.get_all_requirements())
                                   + len(program.benchmark_requirements()))


def test_lep_benchmarks_are_met_on_time(plan):
    _, optimizer, program, schedule = plan

    report = optimizer.audit(program, schedule)

    assert set(report["CMSC_benchmark_45"].applied) == {"CMSC131", "CMSC132", "MATH140"}
    assert {"CMSC330", "CMSC351"} <= set(report["CMSC_benchmark_75"].applied)
    assert report["CMSC_benchmark_75"].satisfied


def test_free_electives_are_scheduled(plan):
    _, optimizer, program, schedule = plan

    electives = optimizer.select_courses(program).electives

    assert electives and set(electives) <= set(schedule.get_all_courses())


def test_concentration_is_twelve_upper_level_credits_in_one_non_cs_department(plan):
    catalog, optimizer, program, schedule = plan

    result = optimizer.audit(program, schedule)["upper_level_concentration"]

    assert result.credits >= 12
    assert len({catalog.department(c) for c in result.applied}) == 1
    for code in result.applied:
        assert catalog.department(code) != "CMSC" and 300 <= catalog.course_number(code) <= 499


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


def test_robotics_minor_reuses_a_concentration_course_for_linear_algebra():
    loader = DataLoader(SAMPLE_DATA)
    optimizer = ScheduleOptimizer(loader.load_catalog())
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="CS + Robotics", primary_major="CMSC"),
        primary_major=loader.load_major("CMSC"),
        minors=[loader.load_minor("RAS")],
        gen_ed_requirements=loader.load_gen_eds(),
    )

    report = optimizer.audit(program, optimizer.optimize_schedule(program))

    # MATH240 is the major's; the ULC may overlap with a minor, so MATH461 counts twice
    assert report["ras_linear_algebra"].applied == ("MATH461",)
    assert "MATH461" in report["upper_level_concentration"].applied


def test_robotics_minor_shares_at_most_two_courses_with_the_major():
    loader = DataLoader(SAMPLE_DATA)
    optimizer = ScheduleOptimizer(loader.load_catalog())
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="CS + Robotics", primary_major="CMSC"),
        primary_major=loader.load_major("CMSC"),
        minors=[loader.load_minor("RAS")],
        gen_ed_requirements=loader.load_gen_eds(),
    )
    owned = program.owned_requirements()

    selection = optimizer.select_courses(program)
    picks = {kind: {c for path, codes in selection.by_requirement.items()
                    if owned[path[0]][0].kind == kind and owned[path[0]][1].id != "upper_level_concentration"
                    for c in codes}
             for kind in ("major", "minor")}

    # CMSC477 (RAS core) and a technical elective double as major electives
    assert picks["major"] & picks["minor"] == {"CMSC477", "CMSC421"}
