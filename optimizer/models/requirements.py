"""Degree requirements data models."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Union, Tuple
from enum import Enum
import math


class RequirementType(Enum):
    """Type of requirement."""
    COURSE = "course"  # Single specific course
    CHOICE = "choice"  # Pick one from list
    GROUP = "group"  # Pick X courses from list
    CATEGORY = "category"  # Courses from a category/area
    CREDIT_HOURS = "credit_hours"  # Minimum credit hours
    GEN_ED = "gen_ed"  # General education requirement


class DoubleCountRule(Enum):
    """Rules for double counting courses."""
    ALLOWED = "allowed"
    PRIMARY_ONLY = "primary_only"
    NOT_ALLOWED = "not_allowed"
    LIMITED = "limited"


@dataclass
class Requirement:
    """Flexible requirement node."""
    id: str
    name: str
    type: RequirementType
    
    # For COURSE type
    course_code: Optional[str] = None
    
    # For CHOICE type (pick 1 from list)
    choices: Optional[List[Union[str, 'Requirement']]] = None
    
    # For GROUP type (pick X from Y)
    courses: Optional[List[Union[str, 'Requirement']]] = None
    min_courses: Optional[int] = None
    max_courses: Optional[int] = None
    min_credits: Optional[int] = None
    
    # For CATEGORY type
    category: Optional[str] = None
    pattern: Optional[str] = None  # Regex pattern for course matching
    
    # For GEN_ED type
    gen_ed_category: Optional[str] = None  # Gen Ed category code (e.g., "FSAW", "DSHS")
    
    # Constraints
    min_grade: Optional[str] = None
    max_from_same_area: Optional[int] = None
    min_areas: Optional[int] = None
    
    # Double counting
    allows_double_count: bool = True
    double_count_limit: Optional[int] = None
    
    # Additional metadata
    notes: str = ""
    
    def get_required_courses(self) -> List[str]:
        """Get list of all required course codes."""
        courses = []
        
        if self.type == RequirementType.COURSE and self.course_code:
            courses.append(self.course_code)
        elif self.type == RequirementType.CHOICE and self.choices:
            # For choices, we can't determine which will be taken
            pass
        elif self.type == RequirementType.GROUP and self.courses:
            for course in self.courses:
                if isinstance(course, str):
                    courses.append(course)
                elif isinstance(course, Requirement):
                    courses.extend(course.get_required_courses())
        
        return courses


@dataclass
class EligibilityRequirement:
    """Requirements to declare/enter a minor."""
    
    # Academic standing
    min_credits_completed: Optional[int] = None
    min_gpa: Optional[float] = None
    min_semesters_remaining: Optional[int] = None
    
    # Major restrictions
    allowed_majors: Optional[List[str]] = None
    excluded_majors: Optional[List[str]] = None
    
    # Prerequisite courses (supports OR logic)
    prerequisite_courses: Optional[List[Union[str, List[str]]]] = None
    
    # Additional requirements
    requires_permission: bool = False
    application_required: bool = False
    competitive_admission: bool = False
    
    def check_eligibility(self, student: 'StudentProfile') -> Tuple[bool, List[str]]:
        """
        Check if student meets eligibility requirements.
        
        Returns:
            (is_eligible, list_of_reasons_if_not)
        """
        reasons = []
        
        if self.min_credits_completed and student.credits_completed < self.min_credits_completed:
            reasons.append(
                f"Need {self.min_credits_completed} credits (have {student.credits_completed})"
            )
        
        if self.min_gpa and student.gpa < self.min_gpa:
            reasons.append(f"Need {self.min_gpa} GPA (have {student.gpa})")
        
        if self.allowed_majors and student.primary_major not in self.allowed_majors:
            reasons.append(
                f"Major {student.primary_major} not eligible "
                f"(allowed: {', '.join(self.allowed_majors)})"
            )
        
        if self.excluded_majors and student.primary_major in self.excluded_majors:
            reasons.append(f"Major {student.primary_major} not allowed")
        
        if self.min_semesters_remaining:
            remaining = student.calculate_semesters_remaining()
            if remaining < self.min_semesters_remaining:
                reasons.append(
                    f"Need {self.min_semesters_remaining} semesters remaining (have {remaining})"
                )
        
        # Check prerequisite courses
        if self.prerequisite_courses:
            for prereq in self.prerequisite_courses:
                if isinstance(prereq, list):
                    # OR condition - at least one must be satisfied
                    if not any(course in student.completed_courses for course in prereq):
                        reasons.append(f"Missing prerequisites (need one of: {', '.join(prereq)})")
                else:
                    # Single course requirement
                    if prereq not in student.completed_courses:
                        reasons.append(f"Missing prerequisite: {prereq}")
        
        return (len(reasons) == 0, reasons)


@dataclass
class MajorRequirements:
    """Complete major requirement specification."""
    major_code: str
    major_name: str
    department: str = ""
    degree_type: str = "BS"
    
    # Core requirements organized by type
    lower_level: List[Requirement] = field(default_factory=list)
    upper_level: List[Requirement] = field(default_factory=list)
    supporting_courses: List[Requirement] = field(default_factory=list)
    concentration: Optional[Requirement] = None
    
    # Benchmarks (for LEP programs)
    benchmarks: Optional[Dict[int, List[Requirement]]] = None
    
    # Overall constraints
    min_credits: int = 120
    min_major_credits: int = 0
    min_upper_level_credits: int = 0
    min_gpa: float = 2.0
    min_major_gpa: float = 2.0
    
    # Double major rules
    double_count_rules: Optional[Dict[str, DoubleCountRule]] = None


@dataclass
class MinorRequirements:
    """Complete minor requirement specification."""
    minor_code: str
    minor_name: str
    department: str
    
    # Eligibility (checked BEFORE declaration)
    eligibility: EligibilityRequirement
    
    # Core requirements
    core_courses: List[Requirement] = field(default_factory=list)
    supporting_courses: List[Requirement] = field(default_factory=list)
    electives: List[Requirement] = field(default_factory=list)
    
    # Constraints
    min_credits: int = 18
    min_gpa: float = 2.0
    min_grade: str = "C-"
    
    # Completion rules
    must_complete_with_major: bool = True
    max_overlap_with_major: Optional[int] = None
    
    # Course sequence/timing
    course_sequence: Optional[List[List[str]]] = None
    fixed_schedule: bool = False
    
    # Restrictions
    restricted_enrollment: bool = False
    requires_permission_per_course: bool = False
