"""Corequisites: met by a course taken earlier or in the same semester."""

import json
from pathlib import Path

from optimizer.core.balance import balance_credits
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.models.student import StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _cond(type_, *codes):
    return PrerequisiteCondition(type_, courses=list(codes))


def _course(code, credits=3, coreqs=(), needs=(), offered=("Fall", "Spring")):
    return Course(code=code, name=code, credits=credits, offered=list(offered),
                  corequisites=list(coreqs),
                  prerequisites=[_cond(PrerequisiteType.COURSE, *needs)] if needs else [])


def _plan(courses, required, load=(3, 9), **student_kwargs):
    catalog = {c.code: c for c in courses}
    major = MajorRequirements(major_code="M", major_name="M", min_credits=0, lower_level=[
        Requirement(id=c, name=c, type=RequirementType.COURSE, course_code=c) for c in required])
    program = StudentDegreeProgram(primary_major=major, student=StudentProfile(
        student_id="1", name="t", primary_major="M", preferred_credit_load=load, **student_kwargs))
    optimizer = ScheduleOptimizer(catalog)
    schedule = optimizer.optimize_schedule(program)
    term = {c: i for i, s in enumerate(schedule.semesters) for c in s.courses}
    return term, optimizer, program, schedule


def test_loader_reads_corequisites_like_prerequisites():
    catalog = DataLoader(SAMPLE_DATA).load_catalog()

    assert catalog["CMSC131"].corequisites == [_cond(PrerequisiteType.COURSE, "MATH140")]
    # Generated from Testudo's text: "ENAE481 or ENAE483 (if not enrolled in ...)"
    assert catalog["ENAE472"].corequisites == [_cond(PrerequisiteType.OR, "ENAE481", "ENAE483")]
    generated = json.loads((SAMPLE_DATA / "courses/ENAE.json").read_text())
    assert {c["code"]: c["corequisite_text"] for c in generated["courses"]}["ENAE472"].startswith(
        "ENAE481 or ENAE483")


def test_mutual_corequisites_go_in_the_same_semester():
    lab = _course("LAB1", 1, coreqs=[_cond(PrerequisiteType.COURSE, "LEC1")])
    lecture = _course("LEC1", coreqs=[_cond(PrerequisiteType.COURSE, "LAB1")])
    # Fall-only A B C go first; LAB1 alone would fit next to them, LEC1 wouldn't
    courses = [_course(c, offered=["Fall"]) for c in "ABC"] + [_course("D"), _course("E"),
                                                               lecture, lab]

    term, optimizer, program, schedule = _plan(courses, ["A", "B", "C", "D", "E", "LEC1", "LAB1"],
                                               load=(3, 10))

    assert term["LEC1"] == term["LAB1"] == 1
    assert not [e for e in optimizer.validator.validate_schedule(schedule, program.student)[1]
                if "Corequisites" in e]


def test_a_course_waits_until_its_corequisite_can_be_taken_with_it_or_before():
    # B's corequisite A is only offered in Spring, so B can't go in the first Fall
    courses = [_course("A", offered=["Spring"]),
               _course("B", coreqs=[_cond(PrerequisiteType.COURSE, "A")]), _course("C")]

    term, *_ = _plan(courses, ["B", "C", "A"])

    assert term["A"] == term["B"] == 1


def test_an_or_corequisite_takes_the_planned_alternative():
    # Z is the planned alternative, and only offered in Spring: X waits for it
    courses = [_course("X", coreqs=[_cond(PrerequisiteType.OR, "Y", "Z")]), _course("Y"),
               _course("Z", offered=["Spring"])]

    term, _, _, schedule = _plan(courses, ["X", "Z"], load=(3, 6))

    assert "Y" not in term and term["X"] == term["Z"]
    assert schedule.semesters[term["X"]].type == SemesterType.SPRING


def test_selection_adds_a_missing_corequisite():
    courses = [_course("CHEM131", coreqs=[_cond(PrerequisiteType.COURSE, "CHEM132")]),
               _course("CHEM132", 1)]

    term, optimizer, program, _ = _plan(courses, ["CHEM131"])

    assert optimizer.select_courses(program).prerequisites == ("CHEM132",)
    assert term["CHEM131"] == term["CHEM132"] == 0


def test_a_credited_corequisite_counts():
    courses = [_course("CMSC131", coreqs=[_cond(PrerequisiteType.COURSE, "MATH140")]),
               _course("MATH140", 4)]

    term, *_ = _plan(courses, ["CMSC131"], ap_credits={"AP Calculus AB": "MATH140"})

    assert term == {"CMSC131": 0}


def test_balancing_keeps_corequisites_together():
    courses = [_course(c) for c in "ABC"] + [
        _course("LEC", coreqs=[_cond(PrerequisiteType.COURSE, "LAB")]), _course("LAB", 1)]
    catalog = Catalog({c.code: c for c in courses})
    student = StudentProfile(student_id="1", name="t", primary_major="M", preferred_credit_load=(3, 12))
    courses.append(_course("E", 2))
    catalog = Catalog({c.code: c for c in courses})
    schedule = Schedule(semesters=[
        Semester(year=2025, type=SemesterType.FALL, courses=["A", "LEC", "LAB"]),  # 7
        Semester(year=2026, type=SemesterType.SPRING, courses=["C", "E"]),         # 5
    ])

    balance_credits(schedule, catalog, student)

    # Only LAB (1 credit) narrows the gap of 2 on its own, but it must stay with
    # LEC; A trades places with E instead
    assert schedule.semesters[0].courses == ["LEC", "LAB", "E"]
    assert schedule.semesters[1].courses == ["C", "A"]


def test_validator_reports_a_corequisite_taken_later():
    catalog = {c.code: c for c in [_course("CMSC131", coreqs=[_cond(PrerequisiteType.COURSE, "MATH140")]),
                                   _course("MATH140", 4)]}
    schedule = Schedule(semesters=[Semester(year=2025, type=SemesterType.FALL, courses=["CMSC131"]),
                                   Semester(year=2026, type=SemesterType.SPRING, courses=["MATH140"])])
    student = StudentProfile(student_id="1", name="t", primary_major="M")

    _, errors = ScheduleOptimizer(catalog).validator.validate_schedule(schedule, student, 0, 18)

    assert errors == ["Fall 2025: Corequisites not met for CMSC131"]
