"""Tests for the requirement audit (optimizer/core/audit.py)."""

from pathlib import Path

from optimizer.core.audit import audit_requirements
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.course import Course
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.student import StudentDegreeProgram, StudentProfile

COURSE, CHOICE, GROUP, GEN_ED = (RequirementType.COURSE, RequirementType.CHOICE,
                                 RequirementType.GROUP, RequirementType.GEN_ED)


def _catalog(*codes, credits=3, **courses):
    catalog = {code: Course(code=code, name=code, credits=credits) for code in codes}
    catalog.update(courses)
    return catalog


def _req(id, type, **kwargs):
    return Requirement(id=id, name=id, type=type, **kwargs)


def test_course_requirement():
    catalog = _catalog("A", "B")
    req = _req("a", COURSE, course_code="A")

    met = audit_requirements(["A"], [req], catalog)["a"]
    unmet = audit_requirements(["B"], [req], catalog)["a"]

    assert met.satisfied and met.applied == ("A",) and met.credits == 3 and met.reason == ""
    assert not unmet.satisfied and unmet.reason == "missing A"


def test_choice_requirement_takes_one_choice():
    catalog = _catalog("A", "B", "C")
    req = _req("pick", CHOICE, choices=["A", "B"])

    assert audit_requirements(["B", "C"], [req], catalog)["pick"].applied == ("B",)
    unmet = audit_requirements(["C"], [req], catalog)["pick"]
    assert not unmet.satisfied and unmet.reason == "needs one of A, B"


def test_group_needs_min_courses_and_min_credits():
    catalog = _catalog("A", "B", "BIG", credits=3, BIG=Course(code="BIG", name="BIG", credits=4))
    by_count = _req("g", GROUP, courses=["A", "B", "BIG"], min_courses=2)
    by_credits = _req("g", GROUP, courses=["A", "B", "BIG"], min_courses=1, min_credits=7)

    assert audit_requirements(["A", "B", "BIG"], [by_count], catalog)["g"].applied == ("A", "B")
    assert audit_requirements(["A", "B", "BIG"], [by_credits], catalog)["g"].applied == ("A", "B", "BIG")
    short = audit_requirements(["A"], [by_credits], catalog)["g"]
    assert not short.satisfied and short.reason == "needs 7 credits, has 3"


def test_group_without_quantity_needs_every_course():
    catalog = _catalog("A", "B")
    req = _req("all", GROUP, courses=["A", "B"])

    assert audit_requirements(["A", "B"], [req], catalog)["all"].satisfied
    assert audit_requirements(["A"], [req], catalog)["all"].reason == "missing B"


def test_empty_group_is_unmet_unless_it_needs_nothing():
    needs = _req("conc", GROUP, courses=[], min_courses=4, min_credits=12)
    nothing = _req("area", GROUP, courses=["A"], min_courses=0, min_credits=0)

    report = audit_requirements(["A"], [needs, nothing], _catalog("A"))

    assert report["conc"].reason == "lists no courses; needs 4 courses, has 0; needs 12 credits, has 0"
    assert report["area"].satisfied and report["area"].applied == ()


def test_group_areas():
    catalog = {
        code: Course(code=code, name=code, credits=3, areas=[area])
        for code, area in [("A1", "x"), ("A2", "x"), ("A3", "x"), ("B1", "y"), ("C1", "z")]
    }
    req = _req("g", GROUP, courses=list(catalog), min_courses=3, min_areas=3, max_from_same_area=2)

    assert audit_requirements(list(catalog), [req], catalog)["g"].applied == ("A1", "B1", "C1")
    two_areas = audit_requirements(["A1", "A2", "B1"], [req], catalog)["g"]
    assert not two_areas.satisfied and two_areas.reason == "needs courses from 3 areas, has 2"
    capped = _req("g", GROUP, courses=list(catalog), min_courses=3, max_from_same_area=2)
    capped_result = audit_requirements(["A1", "A2", "A3"], [capped], catalog)["g"]
    assert capped_result.applied == ("A1", "A2") and not capped_result.satisfied


def test_nested_requirements():
    catalog = _catalog("A", "B", "C")
    inner = _req("inner", CHOICE, choices=["A", "B"])
    group = _req("outer", GROUP, courses=[inner, "C"])
    choice = _req("either", CHOICE, choices=[_req("c", COURSE, course_code="C")])

    met = audit_requirements(["B", "C"], [group], catalog)["outer"]
    unmet = audit_requirements(["C"], [group], catalog)["outer"]

    assert met.satisfied and met.applied == ("B", "C") and met.nested[0].applied == ("B",)
    assert unmet.reason == "inner unmet (needs one of A, B)"
    assert audit_requirements(["C"], [choice], catalog)["either"].applied == ("C",)


def test_no_double_counting_across_major_requirements():
    catalog = _catalog("X", "Y", "Z")
    first = _req("first", GROUP, courses=["X", "Y", "Z"], min_courses=2)
    extra = _req("extra", GROUP, courses=["X", "Y", "Z"], min_courses=1)
    course = _req("x", COURSE, course_code="X")

    report = audit_requirements(["X", "Y", "Z"], [first, extra], catalog)
    assert report["first"].applied == ("X", "Y") and report["extra"].applied == ("Z",)

    report = audit_requirements(["X", "Y"], [first, extra], catalog)
    assert report["first"].satisfied
    assert report["extra"].reason == "needs 1 courses, has 0"

    report = audit_requirements(["X"], [course, extra], catalog)
    assert not report["extra"].satisfied


def test_greedy_leaves_courses_later_requirements_list():
    catalog = _catalog("X", "Y")
    group = _req("either", GROUP, courses=["X", "Y"], min_courses=1)
    course = _req("x", COURSE, course_code="X")

    report = audit_requirements(["X", "Y"], [group, course], catalog)

    assert report.satisfied and report["either"].applied == ("Y",)


def test_unmet_requirement_releases_its_courses():
    catalog = _catalog("X", "Y")
    too_big = _req("big", GROUP, courses=["X", "Y"], min_courses=3)
    course = _req("x", COURSE, course_code="X")

    report = audit_requirements(["X"], [too_big, course], catalog)

    assert report["big"].applied == ("X",) and not report["big"].satisfied
    assert report["x"].satisfied


def test_equivalent_courses_count_once():
    catalog = _catalog("CMSC131", "CMSC131H", "CMSC132",
                       ENEE150=Course(code="ENEE150", name="Intro", credits=3),
                       CMSC150=Course(code="CMSC150", name="Intro", credits=3))
    honors = _req("131", COURSE, course_code="CMSC131")
    cross_listed = _req("150", COURSE, course_code="CMSC150")
    both = _req("both", GROUP, courses=["CMSC131", "CMSC131H", "CMSC132"], min_courses=2)

    report = audit_requirements(["CMSC131H", "ENEE150"], [honors, cross_listed], catalog)
    assert report["131"].applied == ("CMSC131H",) and report["150"].applied == ("ENEE150",)
    assert not audit_requirements(["CMSC131", "CMSC131H"], [both], catalog)["both"].satisfied


def test_gen_ed_option_locking():
    catalog = {
        "HIST": Course(code="HIST", name="HIST", credits=3,
                       gen_ed_options=[["DSHS"], ["DSHU", "DVUP"]]),
        "ARTS": Course(code="ARTS", name="ARTS", credits=3, gen_ed_options=[["DSHU", "DVUP"]]),
    }
    dshs, dshu, dvup = (_req(c, GEN_ED, gen_ed_category=c) for c in ("DSHS", "DSHU", "DVUP"))
    dshu_two = _req("DSHU2", GEN_ED, gen_ed_category="DSHU", min_courses=2)

    locked = audit_requirements(["HIST"], [dshs, dshu], catalog)
    assert locked["DSHS"].satisfied and not locked["DSHU"].satisfied
    assert locked["DSHU"].reason == "needs 1 DSHU courses, has 0"

    same_option = audit_requirements(["HIST"], [dshu, dvup, dshs], catalog)
    assert same_option["DSHU"].satisfied and same_option["DVUP"].satisfied
    assert not same_option["DSHS"].satisfied

    # A single-option course is preferred, keeping HIST's DSHS option open.
    report = audit_requirements(["ARTS", "HIST"], [dshu, dshs], catalog)
    assert report["DSHU"].applied == ("ARTS",) and report["DSHS"].applied == ("HIST",)
    assert not audit_requirements(["HIST"], [dshs, dshu_two], catalog)["DSHU2"].satisfied


def test_gen_ed_reuses_major_courses_and_dsnl_counts_as_dsns():
    catalog = {
        "LAB": Course(code="LAB", name="LAB", credits=4, gen_ed_options=[["DSNL"]]),
        "SCI": Course(code="SCI", name="SCI", credits=3, gen_ed_options=[["DSNS"]]),
    }
    major = _req("lab", COURSE, course_code="LAB")
    dsnl = _req("dsnl", GEN_ED, gen_ed_category="DSNL", min_credits=4)
    dsns = _req("dsns", GEN_ED, gen_ed_category="DSNS", min_courses=2, min_credits=7)

    report = audit_requirements(["SCI", "LAB"], [major, dsnl, dsns], catalog)

    assert report.satisfied
    assert report["dsnl"].applied == ("LAB",)
    assert report["dsns"].applied == ("LAB", "SCI") and report["dsns"].credits == 7


def test_unsupported_requirement_types_are_unmet():
    req = _req("credits", RequirementType.CREDIT_HOURS, min_credits=120)

    result = audit_requirements(["A"], [req], _catalog("A"))["credits"]

    assert not result.satisfied and result.reason == "credit_hours requirements are not supported"


def test_audit_without_schedule_reports_current_progress():
    student = StudentProfile(student_id="1", name="T", primary_major="TEST",
                             completed_courses={"A": "A"}, ap_credits={"AP": "B"})
    major = MajorRequirements(major_code="TEST", major_name="Test",
                              lower_level=[_req("ab", GROUP, courses=["A", "B", "C"])])
    program = StudentDegreeProgram(student=student, primary_major=major)

    result = ScheduleOptimizer(_catalog("A", "B", "C")).audit(program)["ab"]

    assert result.applied == ("A", "B") and result.reason == "missing C"


def test_cs_plan_satisfies_every_fillable_requirement():
    loader = DataLoader(Path("sample_data"))
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="T", primary_major="CMSC"),
        primary_major=loader.load_major("CMSC"),
        gen_ed_requirements=loader.load_gen_eds(),
    )
    optimizer = ScheduleOptimizer(loader.load_catalog())

    report = optimizer.audit(program, optimizer.optimize_schedule(program))

    assert [r.requirement.id for r in report.unmet] == ["upper_level_concentration"]
    assert len(report.results) == len(program.get_all_requirements())
