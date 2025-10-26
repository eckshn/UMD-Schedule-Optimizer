"""Tests for schedule generation and prerequisite sequencing."""

import pytest
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.models.schedule import SemesterType
from optimizer.core.optimizer import ScheduleOptimizer


def test_prerequisite_sequencing():
    """Test that courses are scheduled in prerequisite order."""
    
    # Create a chain of courses: A -> B -> C -> D
    courses = {
        "COURSE_A": Course(
            code="COURSE_A",
            name="Course A",
            credits=4,
            offered=["Fall", "Spring"]
        ),
        "COURSE_B": Course(
            code="COURSE_B",
            name="Course B",
            credits=4,
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["COURSE_A"]
                )
            ],
            offered=["Fall", "Spring"]
        ),
        "COURSE_C": Course(
            code="COURSE_C",
            name="Course C",
            credits=4,
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["COURSE_B"]
                )
            ],
            offered=["Fall", "Spring"]
        ),
        "COURSE_D": Course(
            code="COURSE_D",
            name="Course D",
            credits=4,
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["COURSE_C"]
                )
            ],
            offered=["Fall", "Spring"]
        ),
    }
    
    # Create requirements
    major_reqs = MajorRequirements(
        major_code="TEST",
        major_name="Test Major",
        lower_level=[
            Requirement(
                id="all_courses",
                type=RequirementType.GROUP,
                name="All Courses",
                courses=["COURSE_A", "COURSE_B", "COURSE_C", "COURSE_D"],
                min_credits=16
            )
        ],
        min_credits=120
    )
    
    # Create student
    student = StudentProfile(
        student_id="TEST123",
        name="Test Student",
        primary_major="TEST"
    )
    
    # Create degree program
    program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    # Generate schedule
    optimizer = ScheduleOptimizer(courses)
    schedule = optimizer.optimize_schedule(program, start_year=2025, start_semester=SemesterType.FALL)
    
    # Verify course ordering
    scheduled_courses = {}
    for semester in schedule.semesters:
        semester_idx = (semester.year - 2025) * 2
        if semester.type == SemesterType.SPRING:
            semester_idx += 1
        
        for course_code in semester.courses:
            scheduled_courses[course_code] = semester_idx
    
    # Verify prerequisites are respected
    assert scheduled_courses["COURSE_A"] < scheduled_courses["COURSE_B"]
    assert scheduled_courses["COURSE_B"] < scheduled_courses["COURSE_C"]
    assert scheduled_courses["COURSE_C"] < scheduled_courses["COURSE_D"]
    
    # Verify they're in consecutive semesters (optimal packing)
    assert scheduled_courses["COURSE_B"] == scheduled_courses["COURSE_A"] + 1
    assert scheduled_courses["COURSE_C"] == scheduled_courses["COURSE_B"] + 1
    assert scheduled_courses["COURSE_D"] == scheduled_courses["COURSE_C"] + 1


def test_parallel_prerequisites():
    """Test that independent courses can be scheduled in parallel."""
    
    courses = {
        "PREREQ": Course(
            code="PREREQ",
            name="Prerequisite",
            credits=4,
            offered=["Fall", "Spring"]
        ),
        "COURSE_A": Course(
            code="COURSE_A",
            name="Course A",
            credits=4,
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["PREREQ"]
                )
            ],
            offered=["Fall", "Spring"]
        ),
        "COURSE_B": Course(
            code="COURSE_B",
            name="Course B",
            credits=4,
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["PREREQ"]
                )
            ],
            offered=["Fall", "Spring"]
        ),
    }
    
    major_reqs = MajorRequirements(
        major_code="TEST",
        major_name="Test Major",
        lower_level=[
            Requirement(
                id="all",
                type=RequirementType.GROUP,
                name="All",
                courses=["PREREQ", "COURSE_A", "COURSE_B"],
                min_credits=12
            )
        ],
        min_credits=120
    )
    
    student = StudentProfile(
        student_id="TEST456",
        name="Test Student 2",
        primary_major="TEST"
    )
    
    program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    optimizer = ScheduleOptimizer(courses)
    schedule = optimizer.optimize_schedule(program, start_year=2025)
    
    # Get semester indices
    scheduled_courses = {}
    for semester in schedule.semesters:
        semester_idx = (semester.year - 2025) * 2
        if semester.type == SemesterType.SPRING:
            semester_idx += 1
        
        for course_code in semester.courses:
            scheduled_courses[course_code] = semester_idx
    
    # PREREQ must come before both A and B
    assert scheduled_courses["PREREQ"] < scheduled_courses["COURSE_A"]
    assert scheduled_courses["PREREQ"] < scheduled_courses["COURSE_B"]
    
    # A and B can be in the same semester (parallel)
    assert scheduled_courses["COURSE_A"] == scheduled_courses["COURSE_B"]


def test_semester_availability():
    """Test that courses are only scheduled when offered."""
    
    courses = {
        "FALL_ONLY": Course(
            code="FALL_ONLY",
            name="Fall Only Course",
            credits=4,
            offered=["Fall"]
        ),
        "SPRING_ONLY": Course(
            code="SPRING_ONLY",
            name="Spring Only Course",
            credits=4,
            offered=["Spring"]
        ),
    }
    
    major_reqs = MajorRequirements(
        major_code="TEST",
        major_name="Test Major",
        lower_level=[
            Requirement(
                id="all",
                type=RequirementType.GROUP,
                name="All",
                courses=["FALL_ONLY", "SPRING_ONLY"],
                min_credits=8
            )
        ],
        min_credits=120
    )
    
    student = StudentProfile(
        student_id="TEST789",
        name="Test Student 3",
        primary_major="TEST"
    )
    
    program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    optimizer = ScheduleOptimizer(courses)
    schedule = optimizer.optimize_schedule(program, start_year=2025, start_semester=SemesterType.FALL)
    
    # Find when each course is scheduled
    for semester in schedule.semesters:
        if "FALL_ONLY" in semester.courses:
            assert semester.type == SemesterType.FALL
        if "SPRING_ONLY" in semester.courses:
            assert semester.type == SemesterType.SPRING


def test_year_progression():
    """Test that years progress correctly."""
    
    courses = {
        f"COURSE_{i}": Course(
            code=f"COURSE_{i}",
            name=f"Course {i}",
            credits=4,
            offered=["Fall", "Spring"]
        )
        for i in range(8)
    }
    
    major_reqs = MajorRequirements(
        major_code="TEST",
        major_name="Test Major",
        lower_level=[
            Requirement(
                id="all",
                type=RequirementType.GROUP,
                name="All",
                courses=[f"COURSE_{i}" for i in range(8)],
                min_credits=32
            )
        ],
        min_credits=120
    )
    
    student = StudentProfile(
        student_id="TEST000",
        name="Test Student 4",
        primary_major="TEST"
    )
    
    program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    optimizer = ScheduleOptimizer(courses)
    schedule = optimizer.optimize_schedule(program, start_year=2025, start_semester=SemesterType.FALL)
    
    # Verify year progression
    semesters = schedule.semesters
    assert len(semesters) > 0
    
    # First semester should be Fall 2025
    assert semesters[0].type == SemesterType.FALL
    assert semesters[0].year == 2025
    
    # Verify alternating pattern and year progression
    for i in range(len(semesters) - 1):
        curr_sem = semesters[i]
        next_sem = semesters[i + 1]
        
        if curr_sem.type == SemesterType.FALL:
            # After Fall comes Spring of next year
            assert next_sem.type == SemesterType.SPRING
            assert next_sem.year == curr_sem.year + 1
        else:
            # After Spring comes Fall of same year
            assert next_sem.type == SemesterType.FALL
            assert next_sem.year == curr_sem.year


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
