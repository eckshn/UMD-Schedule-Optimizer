"""Course data model."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


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
    conditions: Optional[List['PrerequisiteCondition']] = None  # For AND type
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
            if not self.courses:
                return True
            course = self.courses[0]
            if course not in completed_courses:
                return False
            if self.min_grade:
                # Simple grade comparison (would need proper grade comparison logic)
                return self._compare_grades(completed_courses[course], self.min_grade)
            return True
            
        elif self.type == PrerequisiteType.OR:
            if not self.courses:
                return True
            return any(course in completed_courses for course in self.courses)
            
        elif self.type == PrerequisiteType.AND:
            if not self.conditions:
                return True
            return all(cond.is_satisfied(completed_courses) for cond in self.conditions)
        
        return False
    
    def _compare_grades(self, grade1: str, grade2: str) -> bool:
        """Compare if grade1 >= grade2."""
        grade_values = {
            'A+': 4.0, 'A': 4.0, 'A-': 3.7,
            'B+': 3.3, 'B': 3.0, 'B-': 2.7,
            'C+': 2.3, 'C': 2.0, 'C-': 1.7,
            'D+': 1.3, 'D': 1.0, 'D-': 0.7,
            'F': 0.0
        }
        return grade_values.get(grade1, 0) >= grade_values.get(grade2, 0)


@dataclass
class Course:
    """Represents a course in the catalog."""
    code: str
    name: str
    credits: int
    description: str = ""
    prerequisites: List[PrerequisiteCondition] = field(default_factory=list)
    corequisites: List[str] = field(default_factory=list)
    level: str = "lower"  # "lower" or "upper"
    areas: List[str] = field(default_factory=list)  # e.g., ["Area1_Systems"]
    offered: List[str] = field(default_factory=lambda: ["Fall", "Spring"])
    typical_sections: int = 1
    difficulty: float = 3.0  # 1-5 scale
    workload_hours: float = 10.0
    gen_ed_categories: List[str] = field(default_factory=list)  # Legacy/flattened format
    gen_ed_options: List[List[str]] = field(default_factory=list)  # New format: [['DSHS'], ['DSHU', 'DVUP']]
    restrictions: List[str] = field(default_factory=list)
    notes: str = ""
    
    def is_available(self, semester: str) -> bool:
        """Check if course is offered in given semester."""
        return semester in self.offered
    
    def prerequisites_satisfied(self, completed_courses: Dict[str, str]) -> bool:
        """Check if all prerequisites are satisfied."""
        if not self.prerequisites:
            return True
        return all(prereq.is_satisfied(completed_courses) for prereq in self.prerequisites)
    
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
