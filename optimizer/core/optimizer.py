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
    
    def _get_course_equivalents(self, course_code: str) -> Set[str]:
        """
        Get all equivalent versions of a course:
        1. Base and honors versions (e.g., AAAS100 and AAAS100H)
        2. Courses with the same name (e.g., CHEM298Q and ARHU270 both named "Quantum Steampunk...")
        """
        equivalents = {course_code}
        
        # Add honors/base version
        if course_code.endswith('H'):
            # If honors version, add base version
            equivalents.add(course_code[:-1])
        else:
            # If base version, add honors version
            equivalents.add(course_code + 'H')
        
        # Add courses with the same name (cross-listed courses)
        if course_code in self.course_catalog:
            course_name = self.course_catalog[course_code].name
            if course_name:
                for other_code, other_course in self.course_catalog.items():
                    if other_course.name == course_name and other_code != course_code:
                        equivalents.add(other_code)
        
        return equivalents
    
    def _is_equivalent_completed(self, course_code: str, completed: Set[str]) -> bool:
        """
        Check if a course or its equivalent (honors/base/same name) is already completed.
        """
        equivalents = self._get_course_equivalents(course_code)
        return bool(equivalents & completed)
    
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
        
        # Track which Gen Ed option was selected for each course
        # Format: {course_code: [list of gen_ed categories from selected option]}
        self._gen_ed_course_assignments = {}
        
        # Get from major requirements
        for req in student_program.get_all_requirements():
            courses = self._extract_courses_from_requirement(req)
            required.update(courses)
        
        # Remove equivalent courses (if both base and honors version are required, keep only one)
        deduplicated = self._deduplicate_equivalent_courses(required)
        
        return list(deduplicated)
    
    def _deduplicate_equivalent_courses(self, courses: Set[str]) -> Set[str]:
        """
        Remove duplicate equivalent courses.
        If both AAAS100 and AAAS100H are in the set, keep only one (preferring non-honors).
        """
        deduplicated = set()
        processed = set()
        
        for course_code in courses:
            # Skip if we've already processed an equivalent
            if course_code in processed:
                continue
            
            # Get all equivalents
            equivalents = self._get_course_equivalents(course_code)
            
            # Check if any equivalent is in the required courses
            matching_equivalents = equivalents & courses
            
            if len(matching_equivalents) > 1:
                # Multiple equivalents found - prefer non-honors version
                if course_code.endswith('H'):
                    base_version = course_code[:-1]
                    if base_version in matching_equivalents:
                        # Skip honors version, keep base
                        processed.update(matching_equivalents)
                        deduplicated.add(base_version)
                        continue
                else:
                    # This is the base version, keep it
                    processed.update(matching_equivalents)
                    deduplicated.add(course_code)
                    continue
            
            # No duplicates or this is the only one
            deduplicated.add(course_code)
            processed.add(course_code)
        
        return deduplicated
    
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
            # For Gen Ed requirements, find courses that can fulfill this category
            # and check if they've already been assigned to a conflicting Gen Ed option
            if requirement.gen_ed_category:
                matching_courses = []
                
                for course_code, course in self.course_catalog.items():
                    # Check if this course has already been assigned to a Gen Ed option
                    if course_code in self._gen_ed_course_assignments:
                        # Check if the assigned option includes the current category
                        if requirement.gen_ed_category in self._gen_ed_course_assignments[course_code]:
                            # This course can still fulfill this requirement
                            matching_courses.append(course_code)
                        # Special case: DSNL courses also fulfill DSNS
                        elif requirement.gen_ed_category == 'DSNS' and 'DSNL' in self._gen_ed_course_assignments[course_code]:
                            # DSNL courses count toward DSNS
                            matching_courses.append(course_code)
                        # Otherwise skip - it's assigned to a different option
                        continue
                    
                    # Course not yet assigned - check if it CAN fulfill this category
                    gen_ed_option = course.get_gen_ed_option_for_category(requirement.gen_ed_category)
                    if gen_ed_option:
                        matching_courses.append(course_code)
                    # Special case: DSNL courses also fulfill DSNS
                    elif requirement.gen_ed_category == 'DSNS':
                        dsnl_option = course.get_gen_ed_option_for_category('DSNL')
                        if dsnl_option:
                            matching_courses.append(course_code)
                
                # Deduplicate equivalent courses (e.g., AAAS100 and AAAS100H) before selecting
                matching_courses_set = self._deduplicate_equivalent_courses(set(matching_courses))
                matching_courses_deduplicated = list(matching_courses_set)
                
                # Select courses to satisfy the requirement
                num_needed = requirement.min_courses if requirement.min_courses else 1
                selected_courses = matching_courses_deduplicated[:num_needed]
                
                # Assign Gen Ed options for selected courses
                for course_code in selected_courses:
                    if course_code not in self._gen_ed_course_assignments:
                        course = self.course_catalog[course_code]
                        gen_ed_option = course.get_gen_ed_option_for_category(requirement.gen_ed_category)
                        if gen_ed_option:
                            self._gen_ed_course_assignments[course_code] = gen_ed_option
                
                courses.update(selected_courses)
        
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
        
        # Track cumulative credits earned (starting credits + scheduled credits)
        cumulative_credits = student.credits_completed
        
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
            upper_level_cs_count = 0  # Track upper-level CS courses in this semester
            
            # Try each remaining course
            for course_code in list(remaining_courses):
                if current_credits >= max_credits:
                    break  # Semester is full
                
                # Skip if equivalent course already completed or scheduled
                if self._is_equivalent_completed(course_code, completed):
                    remaining_courses.discard(course_code)
                    continue
                
                # Check if course exists
                if course_code not in self.course_catalog:
                    remaining_courses.remove(course_code)
                    continue
                
                course = self.course_catalog[course_code]
                
                # Check upper-level CS limit (max 3 per semester)
                is_upper_cs = False
                if course_code.startswith('CMSC') and course.level == 'upper':
                    try:
                        course_num = int(course_code[4:])
                        if 300 <= course_num < 500:
                            is_upper_cs = True
                    except (ValueError, IndexError):
                        if course.level == 'upper':
                            is_upper_cs = True
                
                if is_upper_cs and upper_level_cs_count >= 3:
                    continue  # Already have 3 upper-level CS courses, skip
                
                # Check FSPW requirement: must have 60 credits before taking FSPW courses
                is_fspw = any('FSPW' in option for option in course.gen_ed_options)
                if is_fspw and cumulative_credits < 60:
                    continue  # Cannot take FSPW courses until 60 credits earned
                
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
                    if is_upper_cs:
                        upper_level_cs_count += 1
            
            # Update completed courses and remaining courses
            for course_code in courses_added_this_semester:
                # Mark course and all its equivalents as completed
                completed.update(self._get_course_equivalents(course_code))
                remaining_courses.discard(course_code)
                # Also remove equivalent from remaining if present
                for equiv in self._get_course_equivalents(course_code):
                    remaining_courses.discard(equiv)
                # Update cumulative credits
                if course_code in self.course_catalog:
                    cumulative_credits += self.course_catalog[course_code].credits
            
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
