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
    major = MajorRequirements(major_code="TEST", major_name="Test", lower_level=list(requirements))
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

    selected = ScheduleOptimizer(courses)._get_required_courses(_program(group))

    assert sorted(selected) == ["A1", "B1", "C1"]


def test_groups_do_not_double_count():
    courses = {code: Course(code=code, name=code, credits=3) for code in ["X", "Y", "Z"]}
    first = Requirement(id="first", name="First", type=RequirementType.GROUP,
                        courses=["X", "Y", "Z"], min_courses=2)
    extra = Requirement(id="extra", name="Extra", type=RequirementType.GROUP,
                        courses=["X", "Y", "Z"], min_courses=1)

    selected = ScheduleOptimizer(courses)._get_required_courses(_program(first, extra))

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

    selected = ScheduleOptimizer(courses)._get_required_courses(_program(group))

    assert selected == ["OPEN"]


SCHEDULE_SCRIPT = """
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.student import StudentProfile, StudentDegreeProgram
loader = DataLoader(Path("sample_data"))
program = StudentDegreeProgram(
    student=StudentProfile(student_id="1", name="t", primary_major="CMSC"),
    primary_major=loader.load_major("CMSC"),
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
