"""Tests for evening out semester credits (optimizer/core/balance.py)."""

from optimizer.core.balance import balance_credits
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.models.student import StudentDegreeProgram, StudentProfile


def _course(code, credits=3, needs=(), **kwargs):
    prerequisites = [PrerequisiteCondition(PrerequisiteType.COURSE, courses=list(needs))] if needs else []
    return Course(code=code, name=code, credits=credits, prerequisites=prerequisites, **kwargs)


def _plan(catalog, load=(3, 9), **student_kwargs):
    major = MajorRequirements(major_code="M", major_name="M", min_credits=0, lower_level=[
        Requirement(id=c, name=c, type=RequirementType.COURSE, course_code=c) for c in catalog])
    student = StudentProfile(student_id="1", name="t", primary_major="M",
                             preferred_credit_load=load, **student_kwargs)
    optimizer = ScheduleOptimizer(catalog)
    schedule = optimizer.optimize_schedule(StudentDegreeProgram(student=student, primary_major=major))
    return [s.total_credits(optimizer.course_catalog) for s in schedule.semesters], schedule


def test_balancing_moves_courses_into_the_light_semester_but_keeps_prerequisites_first():
    # Greedy: A B C (9 credits), then D (3); A must stay before D
    loads, schedule = _plan({c.code: c for c in [_course("A"), _course("B"), _course("C"),
                                                  _course("D", needs=["A"])]})

    assert loads == [6, 6]
    term = {c: i for i, s in enumerate(schedule.semesters) for c in s.courses}
    assert term["A"] < term["D"]


def test_balancing_never_adds_semesters_or_moves_a_course_whose_credits_fill_the_gap():
    loads, _ = _plan({c.code: c for c in [_course("A"), _course("B"), _course("C"),
                                           _course("D"), _course("E")]})

    assert loads == [9, 6]  # moving a 3-credit course would just swap the loads


def _semester(year, type_, *codes):
    return Semester(year=year, type=type_, courses=list(codes))


def test_a_swap_keeps_professional_writing_at_sixty_credits():
    courses = [_course(c) for c in "ABCNOPQXYZV"] + [_course("D", 4), _course("E", 4), _course("M", 1),
                                                    _course("W", gen_ed_options=[["FSPW"]])]
    catalog = Catalog({c.code: c for c in courses})
    student = StudentProfile(student_id="1", name="t", primary_major="M", credits_completed=45,
                             preferred_credit_load=(12, 17))
    schedule = Schedule(semesters=[
        _semester(2025, SemesterType.FALL, "A", "B", "C", "D", "E"),        # 17: 62 credits after it
        _semester(2026, SemesterType.SPRING, "W", "X", "Y", "Z", "V"),       # W needs 60 before it
        _semester(2026, SemesterType.FALL, "M", "N", "O", "P", "Q"),         # 13
    ])

    balance_credits(schedule, catalog, student)

    # Moving a 3-credit course out of the first semester would leave 59 credits
    # before W, so A trades places with the 1-credit M instead
    assert [s.total_credits(catalog) for s in schedule.semesters] == [15, 15, 15]
    assert schedule.semesters[0].courses == ["B", "C", "D", "E", "M"]
    assert schedule.semesters[1].courses == ["W", "X", "Y", "Z", "V"]


def test_balancing_keeps_what_the_caller_guards_and_moves_electives_first():
    catalog = Catalog({c.code: c for c in [_course(c) for c in "ABCD"]})
    student = StudentProfile(student_id="1", name="t", primary_major="M",
                             preferred_credit_load=(3, 9))

    def plan():
        return Schedule(semesters=[_semester(2025, SemesterType.FALL, "A", "B", "C"),
                                   _semester(2026, SemesterType.SPRING, "D")])

    guarded = balance_credits(plan(), catalog, student,
                              keeps=lambda s: "A" in s.semesters[0].courses)
    elective = balance_credits(plan(), catalog, student, movable_first={"C"})

    assert guarded.semesters[1].courses == ["D", "B"]  # A would have gone first, by code
    assert elective.semesters[1].courses == ["D", "C"]
