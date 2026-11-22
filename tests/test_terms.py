"""Optional Summer and Winter terms."""

from optimizer.core import rules
from optimizer.core.audit import audit_requests
from optimizer.core.balance import balance_credits
from optimizer.core.optimizer import ScheduleOptimizer, plan_terms
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.models.student import CourseRequest, StudentDegreeProgram, StudentProfile

FALL, SPRING, SUMMER, WINTER = (SemesterType.FALL, SemesterType.SPRING, SemesterType.SUMMER,
                                SemesterType.WINTER)


def _student(**kwargs):
    return StudentProfile(student_id="1", name="t", primary_major="M", **kwargs)


def _course(code, credits=3, offered=("Fall", "Spring"), needs=()):
    prerequisites = [PrerequisiteCondition(PrerequisiteType.COURSE, courses=list(needs))] if needs else []
    return Course(code=code, name=code, credits=credits, offered=list(offered),
                  prerequisites=prerequisites)


def _plan(courses, use_solver=True, **student_kwargs):
    catalog = {c.code: c for c in courses}
    major = MajorRequirements(major_code="M", major_name="M", min_credits=0, lower_level=[
        Requirement(id=c, name=c, type=RequirementType.COURSE, course_code=c) for c in catalog])
    program = StudentDegreeProgram(student=_student(**student_kwargs), primary_major=major)
    optimizer = ScheduleOptimizer(catalog, use_solver=use_solver)
    schedule = optimizer.optimize_schedule(program)
    return {c: str(s) for s in schedule.semesters for c in s.courses}, optimizer, program, schedule


def test_plan_terms_put_winter_after_fall_and_summer_after_spring():
    assert plan_terms(_student(), 2025, FALL)[:3] == [(2025, FALL), (2026, SPRING), (2026, FALL)]
    assert len(plan_terms(_student(), 2025, FALL)) == 8

    both = plan_terms(_student(include_summer=True, include_winter=True), 2025, FALL)
    assert both[:6] == [(2025, FALL), (2026, WINTER), (2026, SPRING), (2026, SUMMER),
                        (2026, FALL), (2027, WINTER)]
    assert both[-1] == (2029, SPRING) and len(both) == 8 + 4 + 3  # none after the last semester

    assert plan_terms(_student(include_summer=True), 2026, SPRING)[:3] == [
        (2026, SPRING), (2026, SUMMER), (2026, FALL)]


def test_schedules_sort_winter_spring_summer_fall():
    schedule = Schedule()
    for year, term in [(2026, FALL), (2026, SUMMER), (2026, WINTER), (2026, SPRING)]:
        schedule.add_semester(Semester(year=year, type=term))

    assert [s.type for s in schedule.semesters] == [WINTER, SPRING, SUMMER, FALL]


def test_term_credit_limits_follow_umd_maximums():
    assert rules.credit_load(_student(), "Fall") == (15, 17)
    assert rules.credit_load(_student(), "Summer") == (0, 8)
    assert rules.credit_load(_student(summer_max_credits=20, winter_max_credits=6), "Summer") == (0, 16)
    assert rules.credit_load(_student(winter_max_credits=6), "Winter") == (0, 4)


def test_summer_courses_are_used_only_when_summer_is_enabled():
    courses = [_course("A", offered=["Fall"]), _course("B", offered=["Summer"], needs=["A"]),
               _course("C", offered=["Fall"], needs=["B"])]

    without, *_ = _plan(courses)
    with_summer, optimizer, program, schedule = _plan(courses, include_summer=True)

    assert "B" not in without  # never offered in a term the plan has
    assert with_summer == {"A": "Fall 2025", "B": "Summer 2026", "C": "Fall 2026"}
    assert not optimizer.validator.validate_schedule(schedule, program.student, 0, 17)[1]


def _by_term(term):
    by_term = {}
    for code, semester in term.items():
        by_term.setdefault(semester, []).append(code)
    return by_term


def test_summer_and_winter_take_one_course_by_default():
    courses = [_course(c, offered=["Fall", "Spring", "Summer", "Winter"]) for c in "ABCDEFGH"]

    term, optimizer, program, schedule = _plan(courses, include_summer=True, include_winter=True,
                                               preferred_credit_load=(3, 6))

    by_term = _by_term(term)
    assert len(by_term["Winter 2026"]) == len(by_term["Summer 2026"]) == 1
    assert not [e for e in optimizer.validator.validate_schedule(schedule, program.student, 0, 6)[1]
                if "Too many" in e]


def test_summer_and_winter_stay_within_their_credit_caps():
    courses = [_course(c, offered=["Fall", "Spring", "Summer", "Winter"]) for c in "ABCDEFGH"]

    # The greedy pass fills each term up to its cap
    term, *_ = _plan(courses, use_solver=False, include_summer=True, include_winter=True,
                     preferred_credit_load=(3, 6), summer_max_credits=6,
                     summer_max_courses=3, winter_max_courses=3)

    by_term = _by_term(term)
    assert len(by_term["Winter 2026"]) == 1   # 4 credits: one 3-credit course
    assert len(by_term["Summer 2026"]) == 2   # 6 credits


def test_validator_uses_summer_and_winter_limits():
    catalog = {c.code: c for c in [_course(c, offered=["Summer", "Winter"]) for c in "ABC"]}
    schedule = Schedule(semesters=[Semester(year=2026, type=WINTER, courses=["A", "B"]),
                                   Semester(year=2026, type=SUMMER, courses=["C"])])

    _, errors = ScheduleOptimizer(catalog).validator.validate_schedule(
        schedule, _student(), 15, 17)

    # No 15-credit minimum for either term
    assert errors == ["Winter 2026: Too many credits 6 (max 4)",
                      "Winter 2026: Too many courses (2 > 1)"]


def test_balancing_leaves_summer_alone():
    catalog = Catalog({c.code: c for c in [_course(c, offered=["Fall", "Spring", "Summer"])
                                           for c in "ABCDE"]})
    schedule = Schedule(semesters=[Semester(year=2025, type=FALL, courses=["A", "B", "C"]),
                                   Semester(year=2026, type=SPRING, courses=["D", "E"]),
                                   Semester(year=2026, type=SUMMER, courses=[])])

    balance_credits(schedule, catalog, _student(include_summer=True, preferred_credit_load=(3, 9)))

    assert schedule.semesters[2].courses == []


def test_a_summer_counts_toward_the_next_semesters_deadline():
    catalog = {c.code: c for c in [_course(c, offered=["Fall", "Spring", "Summer"]) for c in "AB"]}
    semesters = [Semester(year=2025, type=FALL, courses=["A"]),
                 Semester(year=2026, type=SPRING, courses=[]),
                 Semester(year=2026, type=SUMMER, courses=["B"]),
                 Semester(year=2026, type=FALL, courses=[])]

    by_spring, by_fall = audit_requests([CourseRequest("B", by_semester=2),
                                         CourseRequest("B", by_semester=3)], semesters, catalog)

    assert not by_spring.satisfied and by_fall.satisfied
