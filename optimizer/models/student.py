"""Student profile and degree program models."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import math


@dataclass
class StudentProfile:
    """Student's academic profile."""
    student_id: str
    name: str
    primary_major: str
    
    # Academic standing
    credits_completed: int = 0
    gpa: float = 0.0
    current_semester: int = 0  # 0-indexed (0 = first semester)
    
    # Completed coursework
    completed_courses: Dict[str, str] = field(default_factory=dict)  # code -> grade
    in_progress_courses: List[str] = field(default_factory=list)
    
    # Credits from other sources
    ap_credits: Dict[str, str] = field(default_factory=dict)  # AP test -> course equivalency
    transfer_credits: Dict[str, str] = field(default_factory=dict)
    
    # Minors
    declared_minors: List[str] = field(default_factory=list)
    pending_minors: List[str] = field(default_factory=list)
    
    # Preferences
    preferred_credit_load: Tuple[int, int] = (15, 17)  # (min, max) credits per semester
    include_summer: bool = False
    max_difficulty_per_semester: float = 20.0  # Sum of difficulty ratings
    
    def calculate_semesters_remaining(self, total_credits_needed: int = 120) -> int:
        """Calculate how many semesters until graduation."""
        credits_needed = total_credits_needed - self.credits_completed
        avg_credits_per_semester = sum(self.preferred_credit_load) / 2
        return math.ceil(credits_needed / avg_credits_per_semester)
    
    def has_completed(self, course_code: str) -> bool:
        """
        Check if student has completed a course.
        Treats honors courses (with 'H' suffix) as equivalent to base course.
        For example, AAAS100H is considered equivalent to AAAS100.
        """
        # Direct match
        if (course_code in self.completed_courses or 
            course_code in self.ap_credits or 
            course_code in self.transfer_credits):
            return True
        
        # Check if honors version completed (e.g., completed AAAS100H, checking for AAAS100)
        honors_version = course_code + 'H'
        if (honors_version in self.completed_courses or 
            honors_version in self.ap_credits or 
            honors_version in self.transfer_credits):
            return True
        
        # Check if base version completed (e.g., completed AAAS100, checking for AAAS100H)
        if course_code.endswith('H'):
            base_version = course_code[:-1]
            if (base_version in self.completed_courses or 
                base_version in self.ap_credits or 
                base_version in self.transfer_credits):
                return True
        
        return False
    
    def get_grade(self, course_code: str) -> Optional[str]:
        """Get grade for a completed course."""
        if course_code in self.completed_courses:
            return self.completed_courses[course_code]
        elif course_code in self.ap_credits:
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
        
        # Primary major
        requirements.extend(self.primary_major.lower_level)
        requirements.extend(self.primary_major.upper_level)
        requirements.extend(self.primary_major.supporting_courses)
        if self.primary_major.concentration:
            requirements.append(self.primary_major.concentration)
        
        # Secondary major
        if self.secondary_major:
            requirements.extend(self.secondary_major.lower_level)
            requirements.extend(self.secondary_major.upper_level)
            requirements.extend(self.secondary_major.supporting_courses)
            if self.secondary_major.concentration:
                requirements.append(self.secondary_major.concentration)
        
        # Minors
        for minor in self.minors:
            requirements.extend(minor.core_courses)
            requirements.extend(minor.supporting_courses)
            requirements.extend(minor.electives)
        
        # Gen eds
        requirements.extend(self.gen_ed_requirements)
        
        return requirements
    
    def calculate_total_credits_needed(self) -> int:
        """Calculate total credits needed considering overlaps."""
        # Simplified - doesn't account for double counting yet
        return self.primary_major.min_credits
