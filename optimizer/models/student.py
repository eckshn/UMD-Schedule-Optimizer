"""Student profile and degree program models."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Dict, Set, Tuple
import math

from .catalog import honors_pair

if TYPE_CHECKING:
    from .requirements import MajorRequirements, MinorRequirements, Requirement


@dataclass
class StudentProfile:
    """Student's academic profile."""
    student_id: str
    name: str
    primary_major: str
    
    credits_completed: int = 0
    gpa: float = 0.0
    current_semester: int = 0  # 0-indexed (0 = first semester)
    
    completed_courses: Dict[str, str] = field(default_factory=dict)  # code -> grade
    in_progress_courses: List[str] = field(default_factory=list)
    
    ap_credits: Dict[str, str] = field(default_factory=dict)  # AP test -> course equivalency
    transfer_credits: Dict[str, str] = field(default_factory=dict)  # course code -> grade
    
    declared_minors: List[str] = field(default_factory=list)
    pending_minors: List[str] = field(default_factory=list)
    
    preferred_credit_load: Tuple[int, int] = (15, 17)  # (min, max) credits per semester
    include_summer: bool = False
    max_difficulty_per_semester: float = 20.0  # Sum of difficulty ratings
    
    def calculate_semesters_remaining(self, total_credits_needed: int = 120) -> int:
        """Calculate how many semesters until graduation."""
        credits_needed = total_credits_needed - self.credits_completed
        avg_credits_per_semester = sum(self.preferred_credit_load) / 2
        return math.ceil(credits_needed / avg_credits_per_semester)
    
    def credited_courses(self) -> Set[str]:
        """Course codes the student already has credit for (taken, AP or transfer)."""
        return (set(self.completed_courses)
                | set(self.ap_credits.values())
                | set(self.transfer_credits))

    def has_completed(self, course_code: str) -> bool:
        """
        Check if student has credit for a course or its honors/base counterpart
        (AAAS100H is equivalent to AAAS100). Cross-listed equivalents need the
        catalog: see ``Catalog.has_equivalent_in``.
        """
        return not honors_pair(course_code).isdisjoint(self.credited_courses())

    def get_grade(self, course_code: str) -> Optional[str]:
        """Get grade for a completed course."""
        if course_code in self.completed_courses:
            return self.completed_courses[course_code]
        elif course_code in self.ap_credits.values():
            return "P"  # Pass for AP credits
        elif course_code in self.transfer_credits:
            return self.transfer_credits.get(course_code, "P")
        return None


@dataclass
class StudentDegreeProgram:
    """Student's degree program (can have multiple majors/minors)."""
    student: StudentProfile
    primary_major: 'MajorRequirements'
    secondary_major: Optional['MajorRequirements'] = None
    minors: List['MinorRequirements'] = field(default_factory=list)
    gen_ed_requirements: List['Requirement'] = field(default_factory=list)
    
    def get_all_requirements(self) -> List['Requirement']:
        """Get all requirements for the degree program."""
        requirements = []
        
        requirements.extend(self.primary_major.lower_level)
        requirements.extend(self.primary_major.upper_level)
        requirements.extend(self.primary_major.supporting_courses)
        if self.primary_major.concentration:
            requirements.append(self.primary_major.concentration)
        
        if self.secondary_major:
            requirements.extend(self.secondary_major.lower_level)
            requirements.extend(self.secondary_major.upper_level)
            requirements.extend(self.secondary_major.supporting_courses)
            if self.secondary_major.concentration:
                requirements.append(self.secondary_major.concentration)
        
        for minor in self.minors:
            requirements.extend(minor.core_courses)
            requirements.extend(minor.supporting_courses)
            requirements.extend(minor.electives)
        
        requirements.extend(self.gen_ed_requirements)

        # Degree-wide credit minimums count every course, so they come last
        requirements.extend(self.primary_major.credit_requirements())

        return requirements

    def benchmark_requirements(self) -> List[Tuple[int, 'Requirement']]:
        """The benchmarks of the primary and secondary major, in credit order."""
        majors = [m for m in (self.primary_major, self.secondary_major) if m]
        return sorted((b for m in majors for b in m.benchmark_requirements()),
                      key=lambda b: (b[0], b[1].id))
    
    def calculate_total_credits_needed(self) -> int:
        """Calculate total credits needed considering overlaps."""
        # Simplified - doesn't account for double counting yet
        return self.primary_major.min_credits
