"""Degree requirements data models."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Dict, Union, Tuple
from enum import Enum

if TYPE_CHECKING:
    from .student import StudentProfile


class RequirementType(Enum):
    """Type of requirement."""
    COURSE = "course"  # Single specific course
    CHOICE = "choice"  # Pick one from list
    GROUP = "group"  # Pick X courses from list
    CATEGORY = "category"  # Courses from a category/area
    CREDIT_HOURS = "credit_hours"  # Minimum credits/courses of matching courses (CATEGORY filters), no claiming
    DISTRIBUTION = "distribution"  # The program's courses so far (CATEGORY filters) span min_areas areas
    GEN_ED = "gen_ed"  # General education requirement


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
    
    # For CATEGORY type: any catalog course passing every filter that is set
    # (see optimizer/core/categories.py). Needs min_courses and/or min_credits.
    category: Optional[str] = None  # descriptive label only
    pattern: Optional[str] = None  # regex the course code must match from its start
    departments: Optional[List[str]] = None  # only these department prefixes
    exclude_departments: Optional[List[str]] = None  # not these, nor courses cross-listed with them
    min_level: Optional[int] = None  # course number range, inclusive (e.g. 300-499)
    max_level: Optional[int] = None
    has_prerequisite: Optional[str] = None  # course every prerequisite path goes through (Catalog.requires)
    single_department: bool = False  # every applied course from one department
    max_independent_study_credits: Optional[int] = None  # cap on rules.is_independent_study courses

    # False: the courses this requirement applies stay available to later
    # requirements (e.g. a minor's). It still can't use courses that earlier
    # requirements applied.
    exclusive: bool = True
    
    # For GEN_ED type
    gen_ed_category: Optional[str] = None  # Gen Ed category code (e.g., "FSAW", "DSHS")
    
    min_grade: Optional[str] = None
    max_from_same_area: Optional[int] = None
    min_areas: Optional[int] = None
    min_areas_ignore: Optional[List[str]] = None  # areas that don't count toward min_areas
    # At most one course from each of these sets counts (e.g. two capstones)
    mutually_exclusive: Optional[List[List[str]]] = None
    
    notes: str = ""

    def __post_init__(self):
        if self.type == RequirementType.CATEGORY and not (self.min_courses or self.min_credits):
            raise ValueError(
                f"category requirement {self.id!r} must set min_courses or min_credits"
            )
        if self.type == RequirementType.CREDIT_HOURS and not (self.min_credits or self.min_courses):
            raise ValueError(f"credit_hours requirement {self.id!r} must set min_credits or min_courses")
        if self.type == RequirementType.DISTRIBUTION and not self.min_areas:
            raise ValueError(f"distribution requirement {self.id!r} must set min_areas")
        field_name = _REQUIRED_FIELD.get(self.type)
        if field_name is None:
            return
        value = getattr(self, field_name)
        # A GROUP may list no courses yet (e.g. a placeholder); other types need a value.
        if value is None or (not value and self.type != RequirementType.GROUP):
            raise ValueError(
                f"{self.type.value} requirement {self.id!r} must set {field_name}"
            )

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


# The field each requirement type can't do without.
_REQUIRED_FIELD = {
    RequirementType.COURSE: "course_code",
    RequirementType.CHOICE: "choices",
    RequirementType.GROUP: "courses",
    RequirementType.GEN_ED: "gen_ed_category",
}


@dataclass
class EligibilityRequirement:
    """Requirements to declare/enter a minor."""
    
    min_credits_completed: Optional[int] = None
    min_gpa: Optional[float] = None
    min_semesters_remaining: Optional[int] = None
    
    allowed_majors: Optional[List[str]] = None
    excluded_majors: Optional[List[str]] = None
    
    # Prerequisite courses (supports OR logic)
    prerequisite_courses: Optional[List[Union[str, List[str]]]] = None
    
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
        
        if self.prerequisite_courses:
            for prereq in self.prerequisite_courses:
                if isinstance(prereq, list):
                    # OR condition - at least one must be satisfied
                    if not any(course in student.completed_courses for course in prereq):
                        reasons.append(f"Missing prerequisites (need one of: {', '.join(prereq)})")
                else:
                    if prereq not in student.completed_courses:
                        reasons.append(f"Missing prerequisite: {prereq}")
        
        return (len(reasons) == 0, reasons)


@dataclass
class MajorRequirements:
    """Complete major requirement specification."""
    major_code: str
    major_name: str
    track: str = ""  # specialization the requirements are for, if the major has tracks
    department: str = ""
    degree_type: str = "BS"
    
    lower_level: List[Requirement] = field(default_factory=list)
    upper_level: List[Requirement] = field(default_factory=list)
    supporting_courses: List[Requirement] = field(default_factory=list)
    concentration: Optional[Requirement] = None
    
    # Limited-enrollment benchmarks: cumulative credits -> requirements that
    # must be met by the semester in which the student reaches them
    benchmarks: Optional[Dict[int, List[Requirement]]] = None
    
    min_credits: int = 120
    min_major_credits: int = 0
    min_upper_level_credits: int = 0
    min_gpa: float = 2.0
    min_major_gpa: float = 2.0


    def credit_requirements(self) -> List[Requirement]:
        """
        CREDIT_HOURS requirements for the degree-wide credit minimums: total
        credits (``min_credits``) and 300-499 level credits
        (``min_upper_level_credits``). ``min_major_credits`` isn't checked:
        no major sets it, and which courses count would depend on the major.
        """
        requirements = []
        if self.min_credits:
            requirements.append(Requirement(
                id="total_credits", name=f"{self.min_credits} total credits",
                type=RequirementType.CREDIT_HOURS, min_credits=self.min_credits))
        if self.min_upper_level_credits:
            requirements.append(Requirement(
                id="upper_level_credits",
                name=f"{self.min_upper_level_credits} upper-level (300-499) credits",
                type=RequirementType.CREDIT_HOURS, min_credits=self.min_upper_level_credits,
                min_level=300, max_level=499))
        return requirements

    def benchmark_requirements(self) -> List[Tuple[int, Requirement]]:
        """
        Each benchmark as ``(credits, requirement)``, in credit order: a GROUP
        named ``{major_code}_benchmark_{credits}`` that needs every requirement
        listed for it (see ``audit.audit_benchmarks``).
        """
        return [
            (credits, Requirement(
                id=f"{self.major_code}_benchmark_{credits}",
                name=f"{self.major_code} {credits}-credit benchmark",
                type=RequirementType.GROUP, courses=list(requirements)))
            for credits, requirements in sorted((self.benchmarks or {}).items())
        ]


@dataclass
class MinorRequirements:
    """Complete minor requirement specification."""
    minor_code: str
    minor_name: str
    department: str
    
    # Eligibility (checked BEFORE declaration)
    eligibility: EligibilityRequirement
    
    core_courses: List[Requirement] = field(default_factory=list)
    supporting_courses: List[Requirement] = field(default_factory=list)
    electives: List[Requirement] = field(default_factory=list)
    
    min_credits: int = 18
    min_gpa: float = 2.0
    min_grade: str = "C-"
    
    must_complete_with_major: bool = True
    # Most courses that may also count toward a major, on top of UMD's credit
    # limit (rules.within_major_minor_overlap)
    max_overlap_with_major: Optional[int] = None
    
    course_sequence: Optional[List[List[str]]] = None
    fixed_schedule: bool = False
    
    restricted_enrollment: bool = False
    requires_permission_per_course: bool = False
