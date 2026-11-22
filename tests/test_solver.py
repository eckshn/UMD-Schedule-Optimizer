"""The CP-SAT schedule (optimizer/core/solver.py)."""

import pytest

from optimizer.core import solver
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.student import CourseRequest, StudentDegreeProgram, StudentProfile

pytestmark = pytest.mark.skipif(not solver.available(), reason="OR-Tools isn't installed")


def _course(code, credits=3, offered=("Fall", "Spring"), needs=(), coreqs=(), **kwargs):
    def condition(codes):
        return [PrerequisiteCondition(PrerequisiteType.COURSE, courses=list(codes))] if codes else []
    return Course(code=code, name=code, credits=credits, offered=list(offered),
                  prerequisites=condition(needs), corequisites=condition(coreqs), **kwargs)


def _plan(courses, required=None, use_solver=True, **student_kwargs):
    catalog = {c.code: c for c in courses}
    major = MajorRequirements(major_code="M", major_name="M", min_credits=0, lower_level=[
        Requirement(id=c, name=c, type=RequirementType.COURSE, course_code=c)
        for c in (required or catalog)])
    student = StudentProfile(student_id="1", name="t", primary_major="M", **student_kwargs)
    program = StudentDegreeProgram(student=student, primary_major=major)
    optimizer = ScheduleOptimizer(catalog, use_solver=use_solver)
    schedule = optimizer.optimize_schedule(program)
    errors = optimizer.validator.validate_schedule(schedule, student, 0, 99)[1]
    return [s.courses for s in schedule.semesters], [str(s) for s in schedule.semesters], errors


def test_solver_finishes_sooner_than_the_greedy_pass():
    # Two courses a term. Greedy takes A (most dependents) with B in the first
    # Fall, leaving Fall-only C and D for the next Fall, and F after E a year
    # later. The solver waits on A so C fits in the first Fall.
    courses = [_course("A"), _course("B", offered=["Fall"]), _course("C", offered=["Fall"]),
               _course("D", offered=["Fall"], needs=["A", "B"]), _course("E", offered=["Spring"]),
               _course("F", offered=["Fall"], needs=["E"])]

    _, greedy, _ = _plan(courses, use_solver=False, preferred_credit_load=(3, 6))
    solved, terms, errors = _plan(courses, preferred_credit_load=(3, 6))

    assert greedy[-1] == "Fall 2027"
    assert terms == ["Fall 2025", "Spring 2026", "Fall 2026"] and not errors
    assert solved[0] == ["B", "C"]


def test_solver_keeps_requisites_limits_and_prior_credits():
    courses = [_course("A", 4), _course("B", 4, needs=["A"]), _course("C", needs=["B"]),
               _course("LEC", coreqs=["LAB"]), _course("LAB", 1, coreqs=["LEC"]),
               _course("CMSC330"), _course("CMSC351"), _course("CMSC411"), _course("CMSC412"),
               _course("W", gen_ed_options=[["FSPW"]])]

    semesters, _, errors = _plan(courses, preferred_credit_load=(3, 12), credits_completed=50)

    assert not errors  # prerequisites, corequisites, 60 credits before W, at most 3 CMSC 3xx-4xx
    term = {c: i for i, s in enumerate(semesters) for c in s}
    assert term["A"] < term["B"] < term["C"] and term["LEC"] == term["LAB"]
    assert all(len([c for c in s if c.startswith("CMSC")]) <= 3 for s in semesters)


def test_solver_keeps_summer_and_winter_limits():
    courses = [_course(c, offered=["Fall", "Spring", "Summer", "Winter"]) for c in "ABCDEFGH"]

    semesters, terms, errors = _plan(courses, include_summer=True, include_winter=True,
                                     preferred_credit_load=(3, 6))

    assert not [e for e in errors if "Too many" in e]
    assert all(len(s) <= 1 for s, t in zip(semesters, terms) if t.split()[0] in ("Summer", "Winter"))


def test_solver_meets_request_deadlines():
    courses = [_course(c) for c in "ABCDEF"]

    semesters, _, _ = _plan(courses, required=list("ABCDE"), preferred_credit_load=(3, 6),
                            requested_courses=[CourseRequest("F", by_semester=1)])

    assert "F" in semesters[0]


def test_without_ortools_the_greedy_schedule_is_used(monkeypatch):
    courses = [_course(c) for c in "ABC"]
    monkeypatch.setattr(solver, "cp_model", None)

    semesters, _, _ = _plan(courses, preferred_credit_load=(3, 6))

    assert semesters == _plan(courses, use_solver=False, preferred_credit_load=(3, 6))[0]
