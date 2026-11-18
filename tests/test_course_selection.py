"""Tests for how the optimizer chooses courses to satisfy requirements."""

import os
import subprocess
import sys
from pathlib import Path

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import MajorRequirements, Requirement, RequirementType
from optimizer.models.student import StudentDegreeProgram, StudentProfile

REPO_ROOT = Path(__file__).resolve().parent.parent


def _program(*requirements, **student_kwargs):
    student = StudentProfile(student_id="1", name="Test", primary_major="TEST", **student_kwargs)
    # min_credits=0: no total-credit minimum, so no free electives are added
    major = MajorRequirements(major_code="TEST", major_name="Test", min_credits=0,
                              lower_level=list(requirements))
    return StudentDegreeProgram(student=student, primary_major=major)


def test_course_prerequisite_requires_every_listed_course():
    prereq = PrerequisiteCondition(type=PrerequisiteType.COURSE, courses=["CMSC131", "MATH140"])

    assert not prereq.is_satisfied({"CMSC131": "A"})
    assert prereq.is_satisfied({"CMSC131": "A", "MATH140": "B"})


def test_ap_credit_counts_as_completed():
    student = StudentProfile(student_id="1", name="Test", primary_major="CMSC",
                             ap_credits={"AP Calculus AB": "MATH140"})

    assert student.has_completed("MATH140")
    assert student.get_grade("MATH140") == "P"


def test_group_picks_min_courses_across_areas():
    courses = {
        code: Course(code=code, name=code, credits=3, areas=[area])
        for code, area in [("A1", "x"), ("A2", "x"), ("A3", "x"), ("B1", "y"), ("C1", "z")]
    }
    group = Requirement(
        id="pick", name="Pick", type=RequirementType.GROUP,
        courses=list(courses), min_courses=3, min_areas=3, max_from_same_area=2,
    )

    selected = ScheduleOptimizer(courses).select_courses(_program(group)).courses

    assert sorted(selected) == ["A1", "B1", "C1"]


def test_groups_do_not_double_count():
    courses = {code: Course(code=code, name=code, credits=3) for code in ["X", "Y", "Z"]}
    first = Requirement(id="first", name="First", type=RequirementType.GROUP,
                        courses=["X", "Y", "Z"], min_courses=2)
    extra = Requirement(id="extra", name="Extra", type=RequirementType.GROUP,
                        courses=["X", "Y", "Z"], min_courses=1)

    selected = ScheduleOptimizer(courses).select_courses(_program(first, extra)).courses

    assert sorted(selected) == ["X", "Y", "Z"]


def test_group_prefers_courses_with_reachable_prerequisites():
    needs_missing = PrerequisiteCondition(type=PrerequisiteType.COURSE, courses=["NOT_PLANNED"])
    courses = {
        "LOCKED": Course(code="LOCKED", name="Locked", credits=3, prerequisites=[needs_missing]),
        "OPEN": Course(code="OPEN", name="Open", credits=3),
        "NOT_PLANNED": Course(code="NOT_PLANNED", name="Not planned", credits=3),
    }
    group = Requirement(id="pick", name="Pick", type=RequirementType.GROUP,
                        courses=["LOCKED", "OPEN"], min_courses=1)

    selected = ScheduleOptimizer(courses).select_courses(_program(group)).courses

    assert selected == ("OPEN",)



def test_selection_maps_each_requirement_path_to_its_courses():
    courses = {
        "A": Course(code="A", name="A", credits=3),
        "B": Course(code="B", name="B", credits=3, gen_ed_options=[["DSNS"]]),
        "C": Course(code="C", name="C", credits=3),
        "G": Course(code="G", name="G", credits=3, gen_ed_options=[["DSHU"]]),
    }
    # Every requirement shares the id "core": paths keep them apart.
    group = Requirement(id="core", name="Core", type=RequirementType.GROUP, min_courses=1,
                        courses=[Requirement(id="core", name="A", type=RequirementType.COURSE,
                                             course_code="A"), "B", "C"])
    natural = Requirement(id="core", name="DSNS", type=RequirementType.GEN_ED, gen_ed_category="DSNS")
    humanities = Requirement(id="core", name="DSHU", type=RequirementType.GEN_ED, gen_ed_category="DSHU")

    selection = ScheduleOptimizer(courses).select_courses(
        _program(group, natural, humanities, completed_courses={"G": "A"}))

    assert selection.courses == ("A", "B")
    assert dict(selection.by_requirement) == {
        (0,): ("B",), (0, 0): ("A",),  # the group's own pick, and its nested COURSE
        (1,): ("B",),                  # DSNS reuses the major's course
        (2,): ("G",),                  # DSHU reuses a credited course
    }
    assert dict(selection.gen_ed_options) == {"B": ("DSNS",), "G": ("DSHU",)}


def test_select_keeps_no_state_between_calls():
    courses = {
        "X": Course(code="X", name="X", credits=3, gen_ed_options=[["DSNS"], ["DSHU"]]),
        "Y": Course(code="Y", name="Y", credits=3),
    }
    take_x = Requirement(id="x", name="X", type=RequirementType.GROUP, courses=["X", "Y"], min_courses=1)
    natural = Requirement(id="ns", name="DSNS", type=RequirementType.GEN_ED, gen_ed_category="DSNS")
    humanities = Requirement(id="hu", name="DSHU", type=RequirementType.GEN_ED, gen_ed_category="DSHU")
    first, second = _program(take_x, natural), _program(take_x, humanities)
    optimizer = ScheduleOptimizer(courses)

    # The first run claims X and locks it to DSNS; neither may leak into the second.
    earlier = optimizer.select_courses(first)
    selection = optimizer.select_courses(second)

    assert selection.courses == ("X",)
    assert selection.gen_ed_options == {"X": ("DSHU",)}
    assert earlier.gen_ed_options == {"X": ("DSNS",)}  # the second run didn't overwrite it
    assert selection == ScheduleOptimizer(courses).select_courses(second)
    assert optimizer.select_courses(first) == earlier


SCHEDULE_SCRIPT = """
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.student import StudentProfile, StudentDegreeProgram
loader = DataLoader(Path("sample_data"))
program = StudentDegreeProgram(
    student=StudentProfile(student_id="1", name="t", primary_major="CMSC"),
    primary_major=loader.load_major("CMSC"),
    gen_ed_requirements=loader.load_gen_eds(),
)
schedule = ScheduleOptimizer(loader.load_all_courses()).optimize_schedule(program)
print("RESULT", [(str(s), s.courses) for s in schedule.semesters])
"""


def test_schedule_is_identical_across_hash_seeds():
    outputs = set()
    for seed in ("0", "1", "2"):
        result = subprocess.run(
            [sys.executable, "-c", SCHEDULE_SCRIPT],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        outputs.add(next(line for line in result.stdout.splitlines() if line.startswith("RESULT")))

    assert len(outputs) == 1


def _prereq(*codes):
    return [PrerequisiteCondition(type=PrerequisiteType.COURSE, courses=list(codes))]


def test_category_picks_reachable_courses_from_the_department_the_student_knows():
    courses = {
        "MATH141": Course(code="MATH141", name="Calc II", credits=4),
        "MATH401": Course(code="MATH401", name="Lin Alg Apps", credits=3, prerequisites=_prereq("MATH141")),
        "MATH410": Course(code="MATH410", name="Advanced Calc", credits=3, prerequisites=_prereq("MATH141")),
        "MATH499": Course(code="MATH499", name="Topics", credits=3, prerequisites=_prereq("MATH999")),
        "HIST301": Course(code="HIST301", name="History I", credits=3),
        "HIST302": Course(code="HIST302", name="History II", credits=3),
        "CMSC420": Course(code="CMSC420", name="Data Structures", credits=3),
        "MATH210": Course(code="MATH210", name="Lower", credits=3),
    }
    calc = Requirement(id="calc", name="Calc", type=RequirementType.COURSE, course_code="MATH141")
    concentration = Requirement(
        id="conc", name="Concentration", type=RequirementType.CATEGORY, min_level=300,
        max_level=499, exclude_departments=["CMSC"], single_department=True, min_credits=6,
    )

    optimizer = ScheduleOptimizer(courses)
    program = _program(calc, concentration)
    selection = optimizer.select_courses(program)

    # HIST is also fully reachable, but the plan already has MATH courses
    assert selection.by_requirement[(1,)] == ("MATH401", "MATH410")
    assert optimizer.audit(program, optimizer.optimize_schedule(program))["conc"].satisfied


def test_category_falls_back_to_a_department_that_meets_the_minimum():
    courses = {
        "MATH401": Course(code="MATH401", name="Only Math", credits=3),
        "HIST301": Course(code="HIST301", name="History I", credits=3),
        "HIST302": Course(code="HIST302", name="History II", credits=3),
    }
    concentration = Requirement(id="conc", name="Conc", type=RequirementType.CATEGORY,
                                min_level=300, single_department=True, min_credits=6)

    selection = ScheduleOptimizer(courses).select_courses(
        _program(concentration, completed_courses={"MATH140": "A"}))

    assert selection.by_requirement[(0,)] == ("HIST301", "HIST302")


def _elective_program(*requirements, min_credits, min_upper_level_credits=0, **student_kwargs):
    student = StudentProfile(student_id="1", name="Test", primary_major="TEST", **student_kwargs)
    major = MajorRequirements(major_code="TEST", major_name="Test", min_credits=min_credits,
                              min_upper_level_credits=min_upper_level_credits,
                              lower_level=list(requirements))
    return StudentDegreeProgram(student=student, primary_major=major)


def test_free_electives_fill_the_credit_minimum_with_takeable_courses():
    courses = {
        "CORE100": Course(code="CORE100", name="Core", credits=3),
        "CORE200": Course(code="CORE200", name="Core 2", credits=3),
        "ARTS100": Course(code="ARTS100", name="Arts", credits=3),
        "AAAA100": Course(code="AAAA100", name="Restricted", credits=3, restrictions=["Majors only"]),
        "AAAA101": Course(code="AAAA101", name="Locked", credits=3, prerequisites=_prereq("ZZZZ999")),
        "AAAA102": Course(code="AAAA102", name="One credit", credits=1),
        "AAAA600": Course(code="AAAA600", name="Graduate", credits=3),
        "AAAA103": Course(code="AAAA103", name="Never offered", credits=3, offered=[]),
    }
    core = Requirement(id="core", name="Core", type=RequirementType.COURSE, course_code="CORE100")

    selection = ScheduleOptimizer(courses).select_courses(_elective_program(core, min_credits=9))

    # Restricted, unreachable, odd-credit, graduate and unoffered courses lose out;
    # CORE200 wins the tie with ARTS100 because the plan already has a CORE course
    assert selection.electives == ("CORE200", "ARTS100")
    assert selection.courses == ("CORE100", "CORE200", "ARTS100")


def test_upper_level_minimum_is_filled_first_and_counts_toward_the_total():
    courses = {code: Course(code=code, name=code, credits=3)
               for code in ["BASE100", "BASE101", "BASE102", "BASE301", "BASE302"]}

    selection = ScheduleOptimizer(courses).select_courses(
        _elective_program(min_credits=9, min_upper_level_credits=6))

    assert selection.electives == ("BASE301", "BASE302", "BASE100")


def test_earned_credits_reduce_free_electives():
    courses = {code: Course(code=code, name=code, credits=3) for code in ["A100", "A101", "A102"]}

    none_earned = ScheduleOptimizer(courses).select_courses(_elective_program(min_credits=9))
    six_earned = ScheduleOptimizer(courses).select_courses(
        _elective_program(min_credits=9, credits_completed=6))

    assert len(none_earned.electives) == 3 and six_earned.electives == ("A100",)


def test_required_courses_are_scheduled_before_free_electives():
    # Fall-only electives would otherwise go first (fewer offered terms win ties)
    courses = {code: Course(code=code, name=code, credits=3, offered=offered)
               for code, offered in [("AAAA100", ["Fall"]), ("AAAA101", ["Fall"]),
                                     ("REQ100", ["Fall", "Spring"]), ("REQ101", ["Fall", "Spring"])]}
    required = Requirement(id="req", name="Req", type=RequirementType.GROUP,
                           courses=["REQ100", "REQ101"])
    program = _elective_program(required, min_credits=12,
                                preferred_credit_load=(3, 6))

    schedule = ScheduleOptimizer(courses).optimize_schedule(program)

    assert schedule.semesters[0].courses == ["REQ100", "REQ101"]
