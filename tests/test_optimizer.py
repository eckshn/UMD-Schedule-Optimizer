"""Basic tests for the schedule optimizer."""

from pathlib import Path

import pytest
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.requirements import (EligibilityRequirement, MajorRequirements,
                                           MinorRequirements, Requirement, RequirementType)
from optimizer.models.student import StudentDegreeProgram, StudentProfile
from optimizer.models.schedule import Schedule, Semester, SemesterType
from optimizer.core.graph import PrerequisiteGraph
from optimizer.core.optimizer import ScheduleOptimizer


def test_course_creation():
    """Test creating a basic course."""
    course = Course(
        code="CMSC131",
        name="Object-Oriented Programming I",
        credits=4,
        description="Intro to programming"
    )
    
    assert course.code == "CMSC131"
    assert course.credits == 4
    assert course.is_available("Fall")


def test_prerequisite_simple():
    """Test simple prerequisite checking."""
    prereq = PrerequisiteCondition(
        type=PrerequisiteType.COURSE,
        courses=["CMSC131"],
        min_grade="C-"
    )
    
    completed = {"CMSC131": "B"}
    assert prereq.is_satisfied(completed)
    
    assert not prereq.is_satisfied({})


def test_prerequisite_or():
    """Test OR prerequisite logic."""
    prereq = PrerequisiteCondition(
        type=PrerequisiteType.OR,
        courses=["MATH140", "MATH220"]
    )
    
    assert prereq.is_satisfied({"MATH140": "A"})
    assert prereq.is_satisfied({"MATH220": "B"})
    assert prereq.is_satisfied({"MATH140": "A", "MATH220": "B"})
    
    assert not prereq.is_satisfied({})


def test_student_profile():
    """Test student profile creation."""
    student = StudentProfile(
        student_id="12345",
        name="Test Student",
        primary_major="CMSC",
        credits_completed=30,
        gpa=3.5
    )
    
    student.completed_courses["CMSC131"] = "A"
    student.completed_courses["CMSC132"] = "B"
    
    assert student.has_completed("CMSC131")
    assert student.has_completed("CMSC132")
    assert not student.has_completed("CMSC330")
    assert student.get_grade("CMSC131") == "A"


def test_semester_creation():
    """Test semester creation and course management."""
    semester = Semester(year=2025, type=SemesterType.FALL)
    
    semester.add_course("CMSC131")
    semester.add_course("MATH140")
    
    assert len(semester.courses) == 2
    assert "CMSC131" in semester.courses
    
    semester.remove_course("CMSC131")
    assert len(semester.courses) == 1


def test_schedule_creation():
    """Test schedule creation."""
    schedule = Schedule()
    
    fall_2025 = Semester(year=2025, type=SemesterType.FALL)
    fall_2025.add_course("CMSC131")
    fall_2025.add_course("MATH140")
    
    spring_2026 = Semester(year=2026, type=SemesterType.SPRING)
    spring_2026.add_course("CMSC132")
    spring_2026.add_course("MATH141")
    
    schedule.add_semester(fall_2025)
    schedule.add_semester(spring_2026)
    
    assert len(schedule.semesters) == 2
    all_courses = schedule.get_all_courses()
    assert len(all_courses) == 4


def test_prerequisite_graph():
    """Test prerequisite graph construction."""
    # Create simple course chain: 131 -> 132 -> 216
    course131 = Course(code="CMSC131", name="OOP I", credits=4)
    
    course132 = Course(
        code="CMSC132",
        name="OOP II",
        credits=4,
        prerequisites=[
            PrerequisiteCondition(
                type=PrerequisiteType.COURSE,
                courses=["CMSC131"]
            )
        ]
    )
    
    course216 = Course(
        code="CMSC216",
        name="Intro to Systems",
        credits=4,
        prerequisites=[
            PrerequisiteCondition(
                type=PrerequisiteType.COURSE,
                courses=["CMSC132"]
            )
        ]
    )
    
    courses = {
        "CMSC131": course131,
        "CMSC132": course132,
        "CMSC216": course216
    }
    
    graph = PrerequisiteGraph(courses)
    
    prereqs_132 = graph.get_prerequisites("CMSC132")
    assert "CMSC131" in prereqs_132
    
    all_prereqs_216 = graph.get_all_prerequisites("CMSC216")
    assert "CMSC131" in all_prereqs_216
    assert "CMSC132" in all_prereqs_216
    
    ordered = graph.topological_sort(["CMSC216", "CMSC131", "CMSC132"])
    assert ordered.index("CMSC131") < ordered.index("CMSC132")
    assert ordered.index("CMSC132") < ordered.index("CMSC216")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_or_prerequisite_can_hold_nested_conditions():
    from optimizer.models.catalog import Catalog
    from optimizer.data.loader import DataLoader
    loader = DataLoader(Path("."))
    condition = loader._parse_prerequisite(
        {"type": "or", "courses": ["A"], "conditions": [{"type": "and", "conditions": [
            {"type": "course", "courses": ["B"]}, {"type": "course", "courses": ["C"]}]}]})

    assert condition.is_satisfied({"A": "A"})
    assert condition.is_satisfied({"B": "A", "C": "A"})
    assert not condition.is_satisfied({"B": "A"})

    catalog = Catalog({code: Course(code=code, name=code, credits=3) for code in "ABC"}
                      | {"X": Course(code="X", name="X", credits=3, prerequisites=[condition])})
    assert not catalog.requires("X", "B")  # A is an alternative


def test_program_prerequisite_overrides_replace_the_catalogs():
    def needs(*codes):
        return [PrerequisiteCondition(type=PrerequisiteType.COURSE, courses=list(codes))]

    catalog = {code: Course(code=code, name=code, credits=3, prerequisites=prereqs)
               for code, prereqs in [("AAAA100", []), ("AAAA200", []), ("AAAA300", []),
                                     ("AAAA400", needs("AAAA100"))]}
    major = MajorRequirements(major_code="AAAA", major_name="A", min_credits=0, lower_level=[
        Requirement(id=c, name=c, type=RequirementType.COURSE, course_code=c)
        for c in ["AAAA400", "AAAA200"]])
    minor = MinorRequirements(minor_code="M", minor_name="M", department="",
                              eligibility=EligibilityRequirement(),
                              prerequisite_overrides={"AAAA400": needs("AAAA200")})
    program = StudentDegreeProgram(student=StudentProfile(student_id="1", name="t",
                                                          primary_major="AAAA",
                                                          preferred_credit_load=(3, 6)),
                                   primary_major=major, minors=[minor])
    optimizer = ScheduleOptimizer(catalog)

    term = {c: i for i, s in enumerate(optimizer.optimize_schedule(program).semesters)
            for c in s.courses}
    # The minor's prerequisite, not the catalog's AAAA100 (which would be added)
    assert sorted(term) == ["AAAA200", "AAAA400"] and term["AAAA200"] < term["AAAA400"]
    assert optimizer.audit(program).results  # audits with the program's catalog too
    assert optimizer.course_catalog["AAAA400"].prerequisites == needs("AAAA100")

    # A second program with its own prerequisites: either program's are enough
    major.prerequisite_overrides = {"AAAA400": needs("AAAA300")}
    combined = program.prerequisite_overrides()["AAAA400"]
    assert len(combined) == 1 and combined[0].type == PrerequisiteType.OR
    assert [c.conditions for c in combined[0].conditions] == [needs("AAAA300"), needs("AAAA200")]
