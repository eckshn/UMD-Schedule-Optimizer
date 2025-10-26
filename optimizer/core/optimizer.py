"""Main schedule optimization engine."""

from typing import Dict, List, Set, Optional
from ..models.course import Course
from ..models.schedule import Schedule, Semester, SemesterType
from ..models.student import StudentProfile, StudentDegreeProgram
from ..models.requirements import Requirement, RequirementType
from .graph import PrerequisiteGraph
from .constraints import ConstraintValidator


class ScheduleOptimizer:
    """Optimizes course schedules for students."""
    
    def __init__(self, course_catalog: Dict[str, Course]):
        """
        Initialize the optimizer.
        
        Args:
            course_catalog: Dictionary of all available courses
        """
        self.course_catalog = course_catalog
        self.prereq_graph = PrerequisiteGraph(course_catalog)
        self.validator = ConstraintValidator(course_catalog)
    
    def optimize_schedule(self, student_program: StudentDegreeProgram,
                         start_year: int = 2025,
                         start_semester: SemesterType = SemesterType.FALL) -> Schedule:
        """
        Generate an optimized 4-year schedule.
        
        Args:
            student_program: Student's degree program and profile
            start_year: Starting year
            start_semester: Starting semester type
            
        Returns:
            Optimized schedule
        """
        # Phase 1: Determine required courses
        required_courses = self._get_required_courses(student_program)
        
        # Phase 2: Filter out already completed courses
        student = student_program.student
        remaining_courses = [
            c for c in required_courses 
            if not student.has_completed(c)
        ]
        
        # Phase 3: Sort courses by prerequisites (topological sort)
        ordered_courses = self.prereq_graph.topological_sort(remaining_courses)
        
        # Phase 4: Generate semester schedule
        schedule = self._assign_courses_to_semesters(
            ordered_courses,
            student,
            start_year,
            start_semester
        )
        
        # Phase 5: Validate and refine
        is_valid, errors = self.validator.validate_schedule(
            schedule,
            student,
            student.preferred_credit_load[0],
            student.preferred_credit_load[1]
        )
        
        if not is_valid:
            print(f"Warning: Schedule has {len(errors)} validation errors")
            for error in errors[:5]:  # Show first 5 errors
                print(f"  - {error}")
        
        return schedule
    
    def _get_required_courses(self, student_program: StudentDegreeProgram) -> List[str]:
        """Extract all required course codes from requirements."""
        required = set()
        
        # Get from major requirements
        for req in student_program.get_all_requirements():
            courses = self._extract_courses_from_requirement(req)
            required.update(courses)
        
        return list(required)
    
    def _extract_courses_from_requirement(self, requirement: Requirement) -> Set[str]:
        """Recursively extract course codes from a requirement."""
        courses = set()
        
        if requirement.type == RequirementType.COURSE:
            if requirement.course_code:
                courses.add(requirement.course_code)
        
        elif requirement.type == RequirementType.GROUP:
            if requirement.courses:
                for item in requirement.courses:
                    if isinstance(item, str):
                        courses.add(item)
                    elif isinstance(item, Requirement):
                        courses.update(self._extract_courses_from_requirement(item))
        
        elif requirement.type == RequirementType.CHOICE:
            if requirement.choices:
                # For choices, take the first option for now
                # In a real implementation, this would be smarter
                for choice in requirement.choices:
                    if isinstance(choice, str):
                        courses.add(choice)
                        break  # Just take first choice
        
        elif requirement.type == RequirementType.GEN_ED:
            # For Gen Ed requirements, find courses matching the Gen Ed category
            if requirement.gen_ed_category:
                matching_courses = [
                    course_code for course_code, course in self.course_catalog.items()
                    if course.gen_ed_categories and requirement.gen_ed_category in course.gen_ed_categories
                ]
                # Take enough courses to satisfy the requirement
                if requirement.min_courses:
                    courses.update(matching_courses[:requirement.min_courses])
                elif matching_courses:
                    # Take at least one if no minimum specified
                    courses.add(matching_courses[0])
        
        return courses
    
    def _assign_courses_to_semesters(self, courses: List[str],
                                    student: StudentProfile,
                                    start_year: int,
                                    start_semester: SemesterType) -> Schedule:
        """
        Assign courses to semesters using a greedy algorithm.
        
        This is a simplified greedy approach. A production version would use
        constraint programming or other optimization techniques.
        """
        schedule = Schedule()
        completed = set(student.completed_courses.keys())
        completed.update(student.ap_credits.values())
        completed.update(student.transfer_credits.values())
        
        # Track which courses haven't been scheduled yet
        remaining_courses = set(courses)
        
        # Create semester sequence
        current_year = start_year
        current_sem_type = start_semester
        semester_sequence = []
        
        for _ in range(8):  # 8 semesters = 4 years
            semester_sequence.append((current_year, current_sem_type))
            
            if current_sem_type == SemesterType.FALL:
                # Spring comes in the next calendar year
                current_sem_type = SemesterType.SPRING
                current_year += 1
            else:
                # Fall stays in the same year
                current_sem_type = SemesterType.FALL
        
        # Assign courses to semesters
        for year, sem_type in semester_sequence:
            if not remaining_courses:
                break  # All courses scheduled
                
            semester = Semester(year=year, type=sem_type)
            
            # Try to fill this semester
            min_credits, max_credits = student.preferred_credit_load
            current_credits = 0
            courses_added_this_semester = []
            
            # Try each remaining course
            for course_code in list(remaining_courses):
                if current_credits >= max_credits:
                    break  # Semester is full
                
                # Check if course exists
                if course_code not in self.course_catalog:
                    remaining_courses.remove(course_code)
                    continue
                
                course = self.course_catalog[course_code]
                
                # Check prerequisites
                prereqs_met, _ = self.validator.check_prerequisites(course_code, completed)
                if not prereqs_met:
                    continue  # Prerequisites not met yet, try in a future semester
                
                # Check availability
                if not self.validator.check_availability(course_code, sem_type.value):
                    continue  # Not offered this semester, try next semester
                
                # Check if adding would exceed credit limit
                if current_credits + course.credits <= max_credits:
                    semester.add_course(course_code)
                    current_credits += course.credits
                    courses_added_this_semester.append(course_code)
            
            # Update completed courses and remaining courses
            for course_code in courses_added_this_semester:
                completed.add(course_code)
                remaining_courses.remove(course_code)
            
            # Only add semester if it has courses
            if semester.courses:
                schedule.add_semester(semester)
        
        return schedule
    
    def generate_multiple_scenarios(self, student_program: StudentDegreeProgram,
                                    n_scenarios: int = 3) -> List[Schedule]:
        """
        Generate multiple optimized schedule scenarios.
        
        Args:
            student_program: Student's degree program
            n_scenarios: Number of scenarios to generate
            
        Returns:
            List of different optimized schedules
        """
        scenarios = []
        
        # For now, just generate one scenario
        # In a real implementation, this would use different optimization objectives
        base_schedule = self.optimize_schedule(student_program)
        scenarios.append(base_schedule)
        
        return scenarios
    
    def validate_current_progress(self, student_program: StudentDegreeProgram) -> Dict:
        """
        Validate student's current progress against requirements.
        
        Returns:
            Dictionary with progress information
        """
        student = student_program.student
        completed = set(student.completed_courses.keys())
        
        result = {
            "total_credits": student.credits_completed,
            "gpa": student.gpa,
            "requirements_met": [],
            "requirements_pending": [],
            "on_track": True
        }
        
        # Check each requirement
        for req in student_program.get_all_requirements():
            is_met, missing = self.validator.validate_requirement(req, completed)
            
            if is_met:
                result["requirements_met"].append(req.name)
            else:
                result["requirements_pending"].append({
                    "name": req.name,
                    "missing": missing
                })
        
        # Check benchmarks if applicable
        if student_program.primary_major.benchmarks:
            for credits_threshold, benchmark_reqs in student_program.primary_major.benchmarks.items():
                if student.credits_completed >= credits_threshold:
                    # Should have met this benchmark
                    for req in benchmark_reqs:
                        is_met, _ = self.validator.validate_requirement(req, completed)
                        if not is_met:
                            result["on_track"] = False
                            result["requirements_pending"].append({
                                "name": f"Benchmark {credits_threshold}: {req.name}",
                                "missing": [req.course_code] if req.course_code else []
                            })
        
        return result
