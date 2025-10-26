"""Data models for the schedule optimizer."""

from .course import Course, PrerequisiteCondition
from .requirements import (
    Requirement,
    RequirementType,
    MajorRequirements,
    MinorRequirements,
    EligibilityRequirement,
    DoubleCountRule,
)
from .student import StudentProfile, StudentDegreeProgram
from .schedule import Schedule, Semester, SemesterType

__all__ = [
    "Course",
    "PrerequisiteCondition",
    "Requirement",
    "RequirementType",
    "MajorRequirements",
    "MinorRequirements",
    "EligibilityRequirement",
    "DoubleCountRule",
    "StudentProfile",
    "StudentDegreeProgram",
    "Schedule",
    "Semester",
    "SemesterType",
]
