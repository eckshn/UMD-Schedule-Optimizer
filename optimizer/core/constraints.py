"""Constraint validation for schedules."""

from typing import List, Mapping, Set, Tuple
from ..models.catalog import Catalog
from ..models.course import Course
from ..models.schedule import Schedule
from ..models.student import StudentProfile
from . import rules


class ConstraintValidator:
    """Validates schedules against various constraints."""
    
    def __init__(self, course_catalog: Mapping[str, Course]):
        """
        Initialize the constraint validator.
        
        Args:
            course_catalog: All available courses (a ``Catalog`` or a plain dict)
        """
        self.course_catalog = Catalog.of(course_catalog)
    
    def validate_schedule(self, schedule: Schedule, student: StudentProfile,
                         min_credits: int = 12, max_credits: int = 18) -> Tuple[bool, List[str]]:
        """
        Validate a complete schedule.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        schedule_errors = schedule.validate(self.course_catalog, min_credits, max_credits,
                                            already_completed=student.credited_courses())
        errors.extend(schedule_errors)
        
        errors.extend(self._check_duplicate_courses(schedule))
        errors.extend(self._check_difficulty_balance(schedule, student))
        errors.extend(self._check_upper_level_cs_limit(schedule))
        errors.extend(self._check_credit_prerequisites(schedule, student))
        
        return (len(errors) == 0, errors)
    
    def _check_duplicate_courses(self, schedule: Schedule) -> List[str]:
        """Check for duplicate courses in the schedule."""
        errors = []
        all_courses = schedule.get_all_courses()
        
        if len(all_courses) != len(set(all_courses)):
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
        """Check the per-semester cap on upper-level (300-499) CMSC courses."""
        errors = []
        limit = rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER

        for semester in schedule.semesters:
            upper_cs_courses = [
                code for code in semester.courses
                if code in self.course_catalog
                and rules.counts_toward_upper_level_cmsc_cap(self.course_catalog[code])
            ]
            if len(upper_cs_courses) > limit:
                errors.append(
                    f"{semester}: Too many upper-level CS courses ({len(upper_cs_courses)} > {limit}): "
                    f"{', '.join(upper_cs_courses)}"
                )

        return errors

    def _check_credit_prerequisites(self, schedule: Schedule,
                                    student: StudentProfile) -> List[str]:
        """Check courses that need a minimum of cumulative credits (e.g. FSPW at 60)."""
        errors = []
        cumulative_credits = student.credits_completed

        for semester in schedule.semesters:
            for code in semester.courses:
                course = self.course_catalog.get(code)
                required = rules.credits_required_before(course) if course else 0
                if cumulative_credits < required:
                    errors.append(
                        f"{semester}: {code} requires {required} prior credits "
                        f"(has {cumulative_credits})"
                    )
            cumulative_credits += semester.total_credits(self.course_catalog)

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
        
        missing = []
        for prereq in course.prerequisites:
            if not prereq.is_satisfied(completed_with_grades):
                missing.append(str(prereq.courses if prereq.courses else "unknown"))
        
        return (False, missing)
    
    def check_corequisites(self, course_code: str, available: Set[str]) -> bool:
        """Whether ``course_code``'s corequisites are met by ``available`` (earlier or same semester)."""
        course = self.course_catalog.get(course_code)
        return course is not None and course.corequisites_satisfied({c: "A" for c in available})

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
