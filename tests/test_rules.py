"""Tests for the UMD policy rules and their use by the scheduler and the validator."""

from optimizer.core import rules
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.course import Course
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.models.student import StudentDegreeProgram, StudentProfile


def _program(*requirements, **student_kwargs):
    student = StudentProfile(student_id="1", name="Test", primary_major="TEST", **student_kwargs)
    major = MajorRequirements(major_code="TEST", major_name="Test", lower_level=list(requirements))
    return StudentDegreeProgram(student=student, primary_major=major)


def _take_all(codes):
    return Requirement(id="all", type=RequirementType.GROUP, name="All", courses=list(codes))


def _semester(year, sem_type, *codes):
    return Semester(year=year, type=sem_type, courses=list(codes))


def _errors_mentioning(errors, text):
    return [e for e in errors if text in e]


# --- Upper-level CMSC cap -------------------------------------------------

def test_upper_level_cmsc_cap_covers_300_to_499_cmsc_only():
    def counts(code):
        return rules.counts_toward_upper_level_cmsc_cap(Course(code=code, name=code, credits=3))

    assert counts("CMSC330") and counts("CMSC499") and counts("CMSC498A")
    assert not counts("CMSC250") and not counts("CMSC600") and not counts("MATH410")


def test_scheduler_places_at_most_three_upper_level_cmsc_per_semester():
    codes = [f"CMSC4{n}0" for n in range(5)]
    catalog = {c: Course(code=c, name=c, credits=3, level="upper") for c in codes}

    schedule = ScheduleOptimizer(catalog).optimize_schedule(_program(_take_all(codes)))

    assert [len(s.courses) for s in schedule.semesters] == [3, 2]


def test_validator_reports_too_many_upper_level_cmsc():
    codes = [f"CMSC4{n}0" for n in range(4)]
    catalog = {c: Course(code=c, name=c, credits=3, level="upper") for c in codes}
    schedule = Schedule(semesters=[_semester(2025, SemesterType.FALL, *codes)])

    _, errors = ScheduleOptimizer(catalog).validator.validate_schedule(
        schedule, _program().student, min_credits=0)

    assert _errors_mentioning(errors, "Too many upper-level CS courses (4 > 3)")


# --- FSPW needs 60 credits ------------------------------------------------

def _fspw_catalog():
    catalog = {f"FILL{i}": Course(code=f"FILL{i}", name=f"Filler {i}", credits=12) for i in range(5)}
    catalog["ENGL393"] = Course(code="ENGL393", name="Technical Writing", credits=3,
                                gen_ed_options=[["FSPW"]])
    return catalog


def test_credits_required_before_fspw():
    catalog = _fspw_catalog()
    assert rules.credits_required_before(catalog["ENGL393"]) == 60
    assert rules.credits_required_before(catalog["FILL0"]) == 0


def test_scheduler_waits_for_60_credits_before_fspw():
    catalog = _fspw_catalog()
    program = _program(_take_all(catalog))

    schedule = ScheduleOptimizer(catalog).optimize_schedule(program)

    # Five 12-credit fillers reach 60 credits after the fifth semester.
    fspw_semester = next(i for i, s in enumerate(schedule.semesters) if "ENGL393" in s.courses)
    assert fspw_semester == 5


def test_scheduler_counts_credits_already_completed_toward_fspw():
    catalog = _fspw_catalog()
    program = _program(_take_all(catalog), credits_completed=60)

    schedule = ScheduleOptimizer(catalog).optimize_schedule(program)

    assert "ENGL393" in schedule.semesters[0].courses


def test_validator_reports_fspw_before_60_credits():
    catalog = _fspw_catalog()
    validator = ScheduleOptimizer(catalog).validator
    schedule = Schedule(semesters=[
        _semester(2025, SemesterType.FALL, "FILL0", "FILL1", "FILL2", "FILL3"),
        _semester(2026, SemesterType.SPRING, "ENGL393"),
    ])

    def fspw_errors(**student_kwargs):
        _, errors = validator.validate_schedule(schedule, _program(**student_kwargs).student,
                                                min_credits=0, max_credits=99)
        return _errors_mentioning(errors, "ENGL393 requires 60 prior credits")

    assert fspw_errors() == ["Spring 2026: ENGL393 requires 60 prior credits (has 48)"]
    assert fspw_errors(credits_completed=12) == []


# --- DSNL counts toward DSNS ----------------------------------------------

def _gen_ed(category, credits):
    return Requirement(id=category, type=RequirementType.GEN_ED, name=category,
                       gen_ed_category=category, min_courses=1, min_credits=credits)


def test_dsnl_satisfies_dsns():
    assert rules.gen_ed_categories_satisfying("DSNS") == ("DSNS", "DSNL")
    assert rules.gen_ed_categories_satisfying("DSNL") == ("DSNL",)


def test_scheduler_reuses_dsnl_course_for_dsns():
    catalog = {
        "ASTR100": Course(code="ASTR100", name="Astronomy", credits=3, gen_ed_options=[["DSNS"]]),
        "BSCI170": Course(code="BSCI170", name="Lab", credits=4, gen_ed_options=[["DSNL"]]),
    }
    optimizer = ScheduleOptimizer(catalog)

    selected = optimizer._get_required_courses(_program(_gen_ed("DSNL", 4), _gen_ed("DSNS", 3)))

    assert selected == ["BSCI170"]


def test_scheduler_picks_dsnl_course_for_dsns_alone():
    catalog = {"BSCI170": Course(code="BSCI170", name="Lab", credits=4, gen_ed_options=[["DSNL"]])}
    optimizer = ScheduleOptimizer(catalog)

    assert optimizer._get_required_courses(_program(_gen_ed("DSNS", 3))) == ["BSCI170"]
