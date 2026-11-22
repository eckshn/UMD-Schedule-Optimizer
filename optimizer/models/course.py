"""Course data model."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

from .grades import meets_minimum


class PrerequisiteType(Enum):
    """Type of prerequisite condition."""
    COURSE = "course"
    AND = "and"
    OR = "or"


@dataclass
class PrerequisiteCondition:
    """Represents a prerequisite condition (can be nested)."""
    type: PrerequisiteType
    courses: Optional[List[str]] = None  # For COURSE or OR type
    # For AND (all must hold) or OR (alternatives besides ``courses``)
    conditions: Optional[List['PrerequisiteCondition']] = None
    min_grade: Optional[str] = None
    
    def is_satisfied(self, completed_courses: Dict[str, str]) -> bool:
        """
        Check if prerequisite is satisfied by completed courses.
        
        Args:
            completed_courses: Dict mapping course code to grade
            
        Returns:
            True if prerequisite is satisfied
        """
        if self.type == PrerequisiteType.COURSE:
            # Every listed course is required (use OR for alternatives)
            for course in self.courses or []:
                if course not in completed_courses:
                    return False
                if not meets_minimum(completed_courses[course], self.min_grade):
                    return False
            return True
            
        elif self.type == PrerequisiteType.OR:
            if not self.courses and not self.conditions:
                return True
            return (any(course in completed_courses for course in self.courses or [])
                    or any(cond.is_satisfied(completed_courses) for cond in self.conditions or []))
            
        elif self.type == PrerequisiteType.AND:
            if not self.conditions:
                return True
            return all(cond.is_satisfied(completed_courses) for cond in self.conditions)
        
        return False
    
@dataclass
class Course:
    """Represents a course in the catalog."""
    code: str
    name: str
    credits: int
    description: str = ""
    prerequisites: List[PrerequisiteCondition] = field(default_factory=list)
    # Met by courses taken before or in the same semester (same format as prerequisites)
    corequisites: List[PrerequisiteCondition] = field(default_factory=list)
    level: str = "lower"  # "lower" or "upper"
    areas: List[str] = field(default_factory=list)  # e.g., ["Area1_Systems"]
    offered: List[str] = field(default_factory=lambda: ["Fall", "Spring"])
    typical_sections: int = 1
    difficulty: float = 3.0  # 1-5 scale
    workload_hours: float = 10.0
    gen_ed_categories: List[str] = field(default_factory=list)  # Legacy/flattened format
    gen_ed_options: List[List[str]] = field(default_factory=list)  # New format: [['DSHS'], ['DSHU', 'DVUP']]
    restrictions: List[str] = field(default_factory=list)
    # Testudo's "Credit only granted for": this course and others it shares credit with
    credit_only_one_of: List[str] = field(default_factory=list)
    notes: str = ""
    
    def is_available(self, semester: str) -> bool:
        """Check if course is offered in given semester."""
        return semester in self.offered
    
    def prerequisites_satisfied(self, completed_courses: Dict[str, str]) -> bool:
        """Check if all prerequisites are satisfied."""
        if not self.prerequisites:
            return True
        return all(prereq.is_satisfied(completed_courses) for prereq in self.prerequisites)
    
    def corequisites_satisfied(self, available_courses: Dict[str, str]) -> bool:
        """
        Whether every corequisite is met by ``available_courses``: courses
        completed earlier plus those taken in the same semester.
        """
        return all(coreq.is_satisfied(available_courses) for coreq in self.corequisites)

    def get_gen_ed_option_for_category(self, category: str) -> Optional[List[str]]:
        """
        Get the Gen Ed option that includes the given category.
        
        For a course with gen_ed_options = [['DSHS'], ['DSHU', 'DVUP', 'SCIS']]:
        - get_gen_ed_option_for_category('DSHS') returns ['DSHS']
        - get_gen_ed_option_for_category('DVUP') returns ['DSHU', 'DVUP', 'SCIS']
        
        Args:
            category: Gen Ed category code (e.g., 'DSHS')
            
        Returns:
            List of Gen Ed categories in the option, or None if not found
        """
        if not self.gen_ed_options:
            # Fall back to legacy format
            if category in self.gen_ed_categories:
                return [category]
            return None
        
        for option in self.gen_ed_options:
            if category in option:
                return option
        
        return None
    
    def __hash__(self):
        return hash(self.code)
    
    def __eq__(self, other):
        if isinstance(other, Course):
            return self.code == other.code
        return False
