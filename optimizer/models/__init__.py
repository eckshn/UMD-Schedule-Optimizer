"""Data models for the schedule optimizer."""

from .course import Course, PrerequisiteCondition
from .catalog import Catalog
from .requirements import (
    Requirement,
    RequirementType,
    MajorRequirements,
    MinorRequirements,
    EligibilityRequirement,
)
from .student import CourseRequest, RequirementOwner, StudentProfile, StudentDegreeProgram
from .schedule import Schedule, Semester, SemesterType

__all__ = [
    "Course",
    "PrerequisiteCondition",
    "Catalog",
    "Requirement",
    "RequirementType",
    "MajorRequirements",
    "MinorRequirements",
    "EligibilityRequirement",
    "StudentProfile",
    "CourseRequest",
    "StudentDegreeProgram",
    "RequirementOwner",
    "Schedule",
    "Semester",
    "SemesterType",
]
