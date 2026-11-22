"""Minimum grades: real grades for credited courses, retakes, and requirement minimums."""

from pathlib import Path

import pytest

from optimizer.core.audit import audit_requirements
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.grades import earns_credit, meets_minimum
from optimizer.models.requirements import (EligibilityRequirement, MajorRequirements,
                                           MinorRequirements, Requirement, RequirementType)
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.models.student import RequirementOwner, StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _needs(code, minimum="C-"):
    return [PrerequisiteCondition(PrerequisiteType.COURSE, courses=[code], min_grade=minimum)]


def _course(code, credits=3, prerequisites=()):
    return Course(code=code, name=code, credits=credits, prerequisites=list(prerequisites))


def _student(**kwargs):
    return StudentProfile(student_id="1", name="t", primary_major="M", **kwargs)


def _program(requirements, student, minors=()):
    major = MajorRequirements(major_code="M", major_name="M", min_credits=0,
                              lower_level=list(requirements))
    return StudentDegreeProgram(student=student, primary_major=major, minors=list(minors))


def _course_req(code, **kwargs):
    return Requirement(id=code, name=code, type=RequirementType.COURSE, course_code=code, **kwargs)


def test_grade_scale():
    assert meets_minimum("C-", "C-") and meets_minimum("B+", "C-") and not meets_minimum("D+", "C-")
    assert meets_minimum("P", "C-") and meets_minimum("TR", "B")  # AP and transfer credit
    assert earns_credit("D-") and earns_credit("P") and earns_credit(None)
    assert not earns_credit("F") and not earns_credit("W") and not earns_credit("I")


def test_credited_courses_leave_out_courses_without_credit_and_keep_the_best_grade():
    student = _student(completed_courses={"A": "B", "B": "F", "C": "W", "D": "D"},
                       ap_credits={"AP Calc": "D"}, transfer_credits={"E": ""})

    assert student.credited_courses() == {"A", "D", "E"}
    assert student.grades() == {"A": "B", "D": "P", "E": "TR"}  # AP "P" beats the D


def test_prerequisite_minimums_use_real_grades():
    condition = _needs("CMSC132")[0]

    assert condition.is_satisfied({"CMSC132": "C-"}) and condition.is_satisfied({"CMSC132": "P"})
    assert not condition.is_satisfied({"CMSC132": "D"})


def test_a_course_below_a_prerequisite_minimum_is_retaken_first():
    courses = {c.code: c for c in [_course("A"), _course("B", prerequisites=_needs("A"))]}
    program = _program([_course_req("B")], _student(completed_courses={"A": "D"},
                                                   preferred_credit_load=(3, 6)))

    for use_solver in (False, True):
        optimizer = ScheduleOptimizer(courses, use_solver=use_solver)
        assert optimizer.select_courses(program).retakes == ("A",)
        schedule = optimizer.optimize_schedule(program)
        assert [s.courses for s in schedule.semesters] == [["A"], ["B"]]
        assert not optimizer.validator.validate_schedule(schedule, program.student, 0, 6)[1]


def test_validator_reports_a_grade_below_a_prerequisite_minimum():
    courses = {c.code: c for c in [_course("A"), _course("B", prerequisites=_needs("A"))]}
    schedule = Schedule(semesters=[Semester(year=2025, type=SemesterType.FALL, courses=["B"])])

    _, errors = ScheduleOptimizer(courses).validator.validate_schedule(
        schedule, _student(completed_courses={"A": "D"}), 0, 18)

    assert errors == ["Fall 2025: Prerequisites not met for B"]


def test_requirement_minimums_retake_a_course_or_pick_another():
    courses = {c.code: c for c in [_course("A"), _course("B"), _course("C")]}
    student = _student(completed_courses={"A": "D", "B": "D"}, preferred_credit_load=(3, 6))
    must = _course_req("A", min_grade="C-")
    either = Requirement(id="pick", name="pick", type=RequirementType.CHOICE,
                         choices=["B", "C"], min_grade="C-")
    program = _program([must, either], student)
    optimizer = ScheduleOptimizer(courses)

    selection = optimizer.select_courses(program)
    schedule = optimizer.optimize_schedule(program)

    # A has to be retaken; the choice takes C rather than retaking B
    assert selection.retakes == ("A",) and sorted(schedule.get_all_courses()) == ["A", "C"]
    assert optimizer.audit(program, schedule).satisfied
    before = optimizer.audit(program)
    assert before["A"].reason == "missing A (grade D, needs C-)"


def test_a_minor_minimum_grade_applies_to_its_courses():
    minor = MinorRequirements(minor_code="R", minor_name="R", department="",
                              eligibility=EligibilityRequirement(), min_grade="C-",
                              core_courses=[_course_req("ROB1")])
    owner = RequirementOwner("minor", "R", min_grade="C-")
    catalog = {"ROB1": _course("ROB1")}

    assert not audit_requirements(["ROB1"], minor.core_courses, catalog, owners=[owner],
                                  grades={"ROB1": "D+"}).satisfied
    assert audit_requirements(["ROB1"], minor.core_courses, catalog, owners=[owner],
                              grades={"ROB1": "C"}).satisfied

    program = _program([], _student(completed_courses={"ROB1": "D+"}), minors=[minor])
    assert ScheduleOptimizer(catalog).select_courses(program).retakes == ("ROB1",)


def test_cs_student_retakes_cmsc132_and_takes_math140_after_an_f():
    loader = DataLoader(SAMPLE_DATA)
    optimizer = ScheduleOptimizer(loader.load_catalog())
    student = StudentProfile(
        student_id="1", name="t", primary_major="CMSC", credits_completed=15,
        completed_courses={"CMSC131": "A", "CMSC132": "D", "MATH140": "F",
                           "ENGL101": "B", "COMM107": "C"})
    program = StudentDegreeProgram(student=student, primary_major=loader.load_major("CMSC"),
                                   gen_ed_requirements=loader.load_gen_eds())

    schedule = optimizer.optimize_schedule(program)
    term = {c: i for i, s in enumerate(schedule.semesters) for c in s.courses}

    # CMSC216 needs a C- in CMSC132, and the 45-credit benchmark a C- in CMSC132
    assert term["MATH140"] < term["CMSC132"] < term["CMSC216"]
    assert "CMSC131" not in term
    assert [r.requirement.id for r in optimizer.audit(program, schedule).unmet] == []
