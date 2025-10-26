"""Constraint validation for schedules."""

from typing import Dict, List, Set, Tuple
from ..models.course import Course
from ..models.schedule import Schedule, Semester
from ..models.student import StudentProfile
from ..models.requirements import Requirement, RequirementType


class ConstraintValidator:
    """Validates schedules against various constraints."""
    
    def __init__(self, course_catalog: Dict[str, Course]):
        """
        Initialize the constraint validator.
        
        Args:
            course_catalog: Dictionary of all available courses
        """
        self.course_catalog = course_catalog
    
    def validate_schedule(self, schedule: Schedule, student: StudentProfile,
                         min_credits: int = 12, max_credits: int = 18) -> Tuple[bool, List[str]]:
        """
        Validate a complete schedule.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        # Use the schedule's built-in validation
        schedule_errors = schedule.validate(self.course_catalog, min_credits, max_credits)
        errors.extend(schedule_errors)
        
        # Additional validations
        errors.extend(self._check_duplicate_courses(schedule))
        errors.extend(self._check_difficulty_balance(schedule, student))
        errors.extend(self._check_upper_level_cs_limit(schedule))
        
        return (len(errors) == 0, errors)
    
    def _check_duplicate_courses(self, schedule: Schedule) -> List[str]:
        """Check for duplicate courses in the schedule."""
        errors = []
        all_courses = schedule.get_all_courses()
        
        if len(all_courses) != len(set(all_courses)):
            # Find duplicates
            seen = set()
            for course in all_courses:
                if course in seen:
                    errors.append(f"Duplicate course: {course}")
                seen.add(course)
        
        return errors
    
    def _check_difficulty_balance(self, schedule: Schedule, 
                                  student: StudentProfile) -> List[str]:
        """Check if difficulty is balanced across semesters."""
        errors = []
        
        for semester in schedule.semesters:
            difficulty = semester.total_difficulty(self.course_catalog)
            if difficulty > student.max_difficulty_per_semester:
                errors.append(
                    f"{semester}: Too difficult ({difficulty:.1f} > "
                    f"{student.max_difficulty_per_semester})"
                )
        
        return errors
    
    def _check_upper_level_cs_limit(self, schedule: Schedule) -> List[str]:
        """Check that no semester has more than 3 upper-level CS courses (300/400 level)."""
        errors = []
        
        for semester in schedule.semesters:
            upper_cs_courses = []
            for course_code in semester.courses:
                # Check if it's a CMSC course
                if course_code.startswith('CMSC'):
                    course = self.course_catalog.get(course_code)
                    if course and course.level == 'upper':
                        # Also check course number to ensure it's 3XX or 4XX
                        try:
                            course_num = int(course_code[4:])  # Extract number after "CMSC"
                            if 300 <= course_num < 500:
                                upper_cs_courses.append(course_code)
                        except (ValueError, IndexError):
                            # If we can't parse the number, check by level only
                            if course.level == 'upper':
                                upper_cs_courses.append(course_code)
            
            if len(upper_cs_courses) > 3:
                errors.append(
                    f"{semester}: Too many upper-level CS courses ({len(upper_cs_courses)} > 3): "
                    f"{', '.join(upper_cs_courses)}"
                )
        
        return errors
    
    def check_prerequisites(self, course_code: str, 
                           completed: Set[str]) -> Tuple[bool, List[str]]:
        """
        Check if prerequisites are satisfied for a course.
        
        Returns:
            (is_satisfied, list_of_missing_prereqs)
        """
        if course_code not in self.course_catalog:
            return (False, [f"Course {course_code} not found"])
        
        course = self.course_catalog[course_code]
        completed_with_grades = {c: "A" for c in completed}  # Assume passing grades
        
        if course.prerequisites_satisfied(completed_with_grades):
            return (True, [])
        
        # Find missing prerequisites
        missing = []
        for prereq in course.prerequisites:
            if not prereq.is_satisfied(completed_with_grades):
                missing.append(str(prereq.courses if prereq.courses else "unknown"))
        
        return (False, missing)
    
    def check_availability(self, course_code: str, semester_type: str) -> bool:
        """Check if a course is offered in a given semester type."""
        if course_code not in self.course_catalog:
            return False
        
        return self.course_catalog[course_code].is_available(semester_type)
    
    def check_credit_limits(self, courses: List[str], 
                           min_credits: int = 12, 
                           max_credits: int = 18) -> Tuple[bool, int]:
        """
        Check if a set of courses meets credit limits.
        
        Returns:
            (is_valid, total_credits)
        """
        total = sum(self.course_catalog[c].credits for c in courses 
                   if c in self.course_catalog)
        
        return (min_credits <= total <= max_credits, total)
    
    def validate_requirement(self, requirement: Requirement, 
                            completed_courses: Set[str]) -> Tuple[bool, List[str]]:
        """
        Check if a requirement is satisfied.
        
        Returns:
            (is_satisfied, list_of_missing_courses)
        """
        missing = []
        
        if requirement.type == RequirementType.COURSE:
            if requirement.course_code and requirement.course_code not in completed_courses:
                missing.append(requirement.course_code)
        
        elif requirement.type == RequirementType.CHOICE:
            if requirement.choices:
                # Need at least one from the choices
                has_one = False
                for choice in requirement.choices:
                    if isinstance(choice, str) and choice in completed_courses:
                        has_one = True
                        break
                if not has_one:
                    missing.append(f"One of: {', '.join(str(c) for c in requirement.choices)}")
        
        elif requirement.type == RequirementType.GROUP:
            if requirement.courses:
                taken = []
                for course in requirement.courses:
                    if isinstance(course, str) and course in completed_courses:
                        taken.append(course)
                
                if requirement.min_courses and len(taken) < requirement.min_courses:
                    missing.append(
                        f"Need {requirement.min_courses} courses, have {len(taken)}"
                    )
        
        return (len(missing) == 0, missing)
    
    def get_course_conflicts(self, course1: str, course2: str) -> List[str]:
        """
        Check for conflicts between two courses.
        
        Returns:
            List of conflict descriptions
        """
        conflicts = []
        
        if course1 not in self.course_catalog or course2 not in self.course_catalog:
            return conflicts
        
        c1 = self.course_catalog[course1]
        c2 = self.course_catalog[course2]
        
        # Check if courses are the same
        if course1 == course2:
            conflicts.append("Same course")
        
        # Check if one is prerequisite of other
        # (would need prerequisite graph for full check)
        
        return conflicts
