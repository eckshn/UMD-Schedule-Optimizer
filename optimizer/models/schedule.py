"""Schedule data models."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class SemesterType(Enum):
    """Type of semester."""
    FALL = "Fall"
    SPRING = "Spring"
    SUMMER = "Summer"
    WINTER = "Winter"


@dataclass
class Semester:
    """Represents a single semester in the schedule."""
    year: int  # Academic year (e.g., 2025)
    type: SemesterType
    courses: List[str] = field(default_factory=list)  # List of course codes
    
    def total_credits(self, course_catalog: Dict[str, 'Course']) -> int:
        """Calculate total credits for this semester."""
        return sum(course_catalog[code].credits for code in self.courses if code in course_catalog)
    
    def total_difficulty(self, course_catalog: Dict[str, 'Course']) -> float:
        """Calculate total difficulty for this semester."""
        return sum(course_catalog[code].difficulty for code in self.courses if code in course_catalog)
    
    def add_course(self, course_code: str) -> None:
        """Add a course to this semester."""
        if course_code not in self.courses:
            self.courses.append(course_code)
    
    def remove_course(self, course_code: str) -> None:
        """Remove a course from this semester."""
        if course_code in self.courses:
            self.courses.remove(course_code)
    
    def __str__(self) -> str:
        return f"{self.type.value} {self.year}"
    
    def __hash__(self):
        return hash((self.year, self.type))
    
    def __eq__(self, other):
        if isinstance(other, Semester):
            return self.year == other.year and self.type == other.type
        return False


@dataclass
class Schedule:
    """Represents a complete 4-year schedule."""
    semesters: List[Semester] = field(default_factory=list)
    
    def add_semester(self, semester: Semester) -> None:
        """Add a semester to the schedule."""
        if semester not in self.semesters:
            self.semesters.append(semester)
            # Sort chronologically by calendar year: Spring (Jan-May) comes before Fall (Aug-Dec) in same year
            self.semesters.sort(key=lambda s: (
                s.year,
                0 if s.type == SemesterType.SPRING else 1  # Spring in first half, Fall in second half
            ))
    
    def get_semester(self, year: int, semester_type: SemesterType) -> Optional[Semester]:
        """Get a specific semester from the schedule."""
        for sem in self.semesters:
            if sem.year == year and sem.type == semester_type:
                return sem
        return None
    
    def add_course(self, semester_index: int, course_code: str) -> None:
        """Add a course to a semester by index."""
        if 0 <= semester_index < len(self.semesters):
            self.semesters[semester_index].add_course(course_code)
    
    def get_all_courses(self) -> List[str]:
        """Get all courses in the schedule."""
        all_courses = []
        for semester in self.semesters:
            all_courses.extend(semester.courses)
        return all_courses
    
    def total_credits(self, course_catalog: Dict[str, 'Course']) -> int:
        """Calculate total credits in the schedule."""
        return sum(sem.total_credits(course_catalog) for sem in self.semesters)
    
    def validate(self, course_catalog: Dict[str, 'Course'], 
                 min_credits: int = 12, max_credits: int = 18) -> List[str]:
        """
        Validate the schedule.
        
        Returns:
            List of validation error messages
        """
        errors = []
        
        completed = set()
        for i, semester in enumerate(self.semesters):
            # Check credit limits
            credits = semester.total_credits(course_catalog)
            if credits < min_credits:
                errors.append(f"{semester}: Only {credits} credits (min {min_credits})")
            if credits > max_credits:
                errors.append(f"{semester}: Too many credits {credits} (max {max_credits})")
            
            # Check prerequisites
            for course_code in semester.courses:
                if course_code not in course_catalog:
                    errors.append(f"{semester}: Course {course_code} not in catalog")
                    continue
                
                course = course_catalog[course_code]
                if not course.prerequisites_satisfied({c: "A" for c in completed}):
                    errors.append(
                        f"{semester}: Prerequisites not met for {course_code}"
                    )
                
                # Check availability
                if not course.is_available(semester.type.value):
                    errors.append(
                        f"{semester}: {course_code} not offered in {semester.type.value}"
                    )
            
            # Add courses to completed set
            completed.update(semester.courses)
        
        return errors
    
    def __str__(self) -> str:
        result = "Schedule:\n"
        for semester in self.semesters:
            result += f"\n{semester}:\n"
            for course in semester.courses:
                result += f"  - {course}\n"
        return result
