"""Tests for the requirement audit (optimizer/core/audit.py)."""

from optimizer.core.audit import audit_requirements
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
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


def test_credit_hours_count_every_matching_course_without_claiming_it():
    catalog = _catalog("MATH140", "MATH401", "HIST301", credits=4)
    course = _req("calc", COURSE, course_code="MATH401")
    total = _req("total", RequirementType.CREDIT_HOURS, min_credits=12)
    upper = _req("upper", RequirementType.CREDIT_HOURS, min_credits=12, min_level=300, max_level=499)

    report = audit_requirements(["MATH140", "MATH401", "HIST301"], [course, total, upper], catalog)

    assert report["calc"].satisfied
    assert report["total"].satisfied and report["total"].credits == 12
    assert report["total"].applied == ("HIST301", "MATH140", "MATH401")
    assert not report["upper"].satisfied and report["upper"].reason == "needs 12 credits, has 8"


def test_prior_credits_count_only_toward_unfiltered_credit_hours():
    total = _req("total", RequirementType.CREDIT_HOURS, min_credits=10)
    upper = _req("upper", RequirementType.CREDIT_HOURS, min_credits=6, min_level=300)

    report = audit_requirements(["MATH401"], [total, upper], _catalog("MATH401"), prior_credits=7)

    assert report["total"].satisfied and report["total"].credits == 10
    assert not report["upper"].satisfied and report["upper"].credits == 3


def test_program_audit_adds_major_credit_minimums_and_unlisted_credits():
    student = StudentProfile(student_id="1", name="T", primary_major="TEST",
                             completed_courses={"A": "A", "UNKNOWN1": "B"}, credits_completed=30)
    major = MajorRequirements(major_code="TEST", major_name="Test", min_credits=36,
                              min_upper_level_credits=3,
                              lower_level=[_req("a", COURSE, course_code="A")])
    program = StudentDegreeProgram(student=student, primary_major=major)

    report = ScheduleOptimizer(_catalog("A", "B300")).audit(program)

    # 3 credits of A, plus 27 earned in courses the catalog doesn't know about
    assert report["total_credits"].credits == 30 and report["total_credits"].reason == "needs 36 credits, has 30"
    assert report["upper_level_credits"].reason == "needs 3 credits, has 0"


def test_audit_without_schedule_reports_current_progress():
    student = StudentProfile(student_id="1", name="T", primary_major="TEST",
                             completed_courses={"A": "A"}, ap_credits={"AP": "B"})
    major = MajorRequirements(major_code="TEST", major_name="Test",
                              lower_level=[_req("ab", GROUP, courses=["A", "B", "C"])])
    program = StudentDegreeProgram(student=student, primary_major=major)

    result = ScheduleOptimizer(_catalog("A", "B", "C")).audit(program)["ab"]

    assert result.applied == ("A", "B") and result.reason == "missing C"


def _concentration(**kwargs):
    return _req("conc", RequirementType.CATEGORY, min_level=300, max_level=499,
                exclude_departments=["CMSC"], single_department=True, min_credits=6, **kwargs)


def test_category_applies_matching_courses_from_one_department():
    catalog = _catalog("MATH201", "MATH401", "MATH402", "HIST301", "CMSC420", "MATH501")

    report = audit_requirements(["MATH201", "MATH401", "HIST301", "CMSC420", "MATH402", "MATH501"],
                                [_concentration()], catalog)

    assert report["conc"].satisfied and report["conc"].applied == ("MATH401", "MATH402")


def test_category_rejects_split_departments_and_cmsc_cross_lists():
    catalog = _catalog("HIST301", "MATH401",
                       MATH475=Course(code="MATH475", name="Combinatorics", credits=3),
                       CMSC475=Course(code="CMSC475", name="Combinatorics", credits=3))

    result = audit_requirements(["HIST301", "MATH401", "MATH475"], [_concentration()], catalog)["conc"]

    assert not result.satisfied
    assert result.reason == "needs 6 matching credits from one department, has 3"


def test_category_courses_are_not_reused_by_other_requirements():
    catalog = _catalog("MATH401", "MATH402")
    group = _req("g", GROUP, courses=["MATH401"], min_courses=1)

    report = audit_requirements(["MATH401", "MATH402"], [group, _concentration()], catalog)

    assert report["g"].applied == ("MATH401",)
    assert not report["conc"].satisfied and report["conc"].applied == ("MATH402",)


def test_category_with_prerequisite_filter():
    def needs(*codes):
        return [PrerequisiteCondition(type=PrerequisiteType.COURSE, courses=list(codes))]

    catalog = _catalog("MATH141", "STAT100",
                       STAT400=Course(code="STAT400", name="Prob", credits=3, prerequisites=needs("MATH141")))
    stat = _req("stat", RequirementType.CATEGORY, departments=["STAT"], has_prerequisite="MATH141",
                min_courses=1)

    assert audit_requirements(["MATH141", "STAT100", "STAT400"], [stat], catalog)["stat"].applied == ("STAT400",)
    assert not audit_requirements(["MATH141", "STAT100"], [stat], catalog)["stat"].satisfied


def test_category_leaves_courses_a_later_category_needs():
    catalog = _catalog("MATH401", "STAT401")
    math_or_stat = _req("any", RequirementType.CATEGORY, departments=["MATH", "STAT"], min_courses=1)
    math = _req("math", RequirementType.CATEGORY, departments=["MATH"], min_courses=1)

    report = audit_requirements(["MATH401", "STAT401"], [math_or_stat, math], catalog)

    # Code order alone would hand MATH401 to the first requirement and starve the second
    assert report["any"].applied == ("STAT401",) and report["math"].applied == ("MATH401",)
