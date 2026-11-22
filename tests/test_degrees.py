"""
Multiple degrees (StudentDegreeProgram.additional_degrees): 30 more credits
per extra degree and 18 credits in each major no other degree's major counts.
"""

from pathlib import Path

import pytest

from optimizer.core import rules
from optimizer.core.optimizer import REGULAR_SEMESTERS, ScheduleOptimizer, regular_semesters
from optimizer.data.loader import DataLoader
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.student import RequirementOwner, StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _catalog(*codes):
    return Catalog({code: Course(code=code, name=code, credits=3) for code in codes})


def _group(id, codes, **kwargs):
    return Requirement(id=id, name=id, type=RequirementType.GROUP, courses=list(codes), **kwargs)


def _major(code, *requirements, min_credits=0):
    return MajorRequirements(major_code=code, major_name=code, lower_level=list(requirements),
                             min_credits=min_credits)


def _program(primary, majors=(), degrees=()):
    return StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="T", primary_major=primary.major_code),
        primary_major=primary, additional_majors=list(majors), additional_degrees=list(degrees))


def _total(program):
    return next(r for r in program.credit_requirements() if r.id == "total_credits").min_credits


def test_each_extra_degree_adds_thirty_credits():
    a, b, c = (_major(code, min_credits=120) for code in "ABC")

    assert _total(_program(a)) == 120
    assert _total(_program(a, majors=[b])) == 120    # double major: one degree
    assert _total(_program(a, degrees=[b])) == 150   # double degree
    assert _total(_program(a, degrees=[b, c])) == 180
    assert _program(a, degrees=[b, c]).calculate_total_credits_needed() == 180


def test_majors_of_separate_degrees_each_need_unique_credits():
    a, b, c = (_major(code) for code in "ABC")

    owned = _program(a, majors=[b], degrees=[c]).owned_requirements()

    unique = [(o, r.id) for o, r in owned if r.type == RequirementType.UNIQUE_CREDITS]
    assert unique == [(RequirementOwner("major", "A"), "A_unique_credits"),
                      (RequirementOwner("major", "B"), "B_unique_credits"),
                      (RequirementOwner("major", "C", degree=1), "C_unique_credits")]
    assert owned[-3:] == [(o, r) for o, r in owned if r.type == RequirementType.UNIQUE_CREDITS]
    assert all(r.min_credits == rules.MIN_UNIQUE_MAJOR_CREDITS for _, r in owned[-3:])
    assert not any(r.type == RequirementType.UNIQUE_CREDITS
                   for _, r in _program(a, majors=[b]).owned_requirements())


def test_audit_counts_only_courses_no_other_degree_counts():
    shared = [f"S{i}" for i in range(4)]
    own = [f"A{i}" for i in range(6)]
    catalog = _catalog(*shared, *own)
    a = _major("A", _group("a_core", shared + own))
    b = _major("B", _group("b_core", shared))
    optimizer = ScheduleOptimizer(catalog, use_solver=False)

    program = _program(a, degrees=[b])
    program.student.completed_courses = {code: "A" for code in shared + own}
    report = optimizer.audit(program)

    assert report["A_unique_credits"].satisfied
    assert set(report["A_unique_credits"].applied) == set(own)
    assert report["A_unique_credits"].credits == 18
    assert not report["B_unique_credits"].satisfied
    assert "has 0" in report["B_unique_credits"].reason


def test_selection_avoids_another_degrees_courses_when_it_can():
    catalog = _catalog("X", "Y")
    a = _major("A", _group("a_pick", ["X", "Y"], min_courses=1))
    b = _major("B", _group("b_pick", ["X", "Y"], min_courses=1))
    optimizer = ScheduleOptimizer(catalog, use_solver=False)

    double_major = optimizer.select_courses(_program(a, majors=[b])).courses
    double_degree = optimizer.select_courses(_program(a, degrees=[b])).courses

    assert double_major == ("X",)        # one degree: the majors share X
    assert set(double_degree) == {"X", "Y"}


def test_plans_get_more_semesters_for_more_credits():
    a, b = _major("A", min_credits=120), _major("B", min_credits=120)

    assert regular_semesters(_program(a)) == REGULAR_SEMESTERS
    assert regular_semesters(_program(a, degrees=[b])) == 10  # 150 credits at 15


@pytest.fixture(scope="module")
def cs_math_double_degree():
    loader = DataLoader(SAMPLE_DATA)
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="CS + Math", primary_major="CMSC"),
        primary_major=loader.load_major("CMSC"), additional_degrees=[loader.load_major("MATH")],
        gen_ed_requirements=loader.load_gen_eds())
    optimizer = ScheduleOptimizer(loader.load_catalog())
    return optimizer, program, optimizer.optimize_schedule(program)


def test_cs_and_math_double_degree_meets_everything(cs_math_double_degree):
    optimizer, program, schedule = cs_math_double_degree

    report = optimizer.audit(program, schedule)

    assert [(r.requirement.id, r.reason) for r in report.unmet] == []
    assert report["total_credits"].credits >= 150
    assert report["CMSC_unique_credits"].credits >= 18
    assert report["MATH_unique_credits"].credits >= 18
    assert REGULAR_SEMESTERS < len(schedule.semesters) <= 10
