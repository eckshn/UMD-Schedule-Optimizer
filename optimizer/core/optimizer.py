"""Main schedule optimization engine."""

import logging
from typing import List, Mapping, Optional
import networkx as nx
from ..models.catalog import Catalog
from ..models.course import Course
from ..models.schedule import Schedule, Semester, SemesterType
from ..models.student import StudentProfile, StudentDegreeProgram
from .graph import PrerequisiteGraph
from .constraints import ConstraintValidator
from .audit import AuditReport, audit_requirements
from .categories import prior_credits
from .selection import CourseSelector, Selection
from . import rules

logger = logging.getLogger(__name__)


class ScheduleOptimizer:
    """Optimizes course schedules for students."""
    
    def __init__(self, course_catalog: Mapping[str, Course]):
        """
        Initialize the optimizer.
        
        Args:
            course_catalog: All available courses (a ``Catalog`` or a plain dict)
        """
        self.course_catalog = Catalog.of(course_catalog)
        self.prereq_graph = PrerequisiteGraph(self.course_catalog)
        self.validator = ConstraintValidator(self.course_catalog)
        self.selector = CourseSelector(self.course_catalog)

    def select_courses(self, student_program: StudentDegreeProgram) -> Selection:
        """The courses chosen to satisfy the program's requirements (pipeline phase 1)."""
        return self.selector.select(student_program)
    
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
        selection = self.select_courses(student_program)
        required_courses = selection.courses
        
        # Phase 2: Filter out already completed courses
        student = student_program.student
        remaining_courses = [
            c for c in required_courses 
            if not student.has_completed(c)
        ]
        
        # Phase 3: Order courses (long prerequisite chains first, then topological).
        # Free electives go last, so they only fill room required courses leave.
        ordered_courses = self._scheduling_priority(remaining_courses)
        electives = set(selection.electives)
        ordered_courses = ([c for c in ordered_courses if c not in electives]
                           + [c for c in ordered_courses if c in electives])
        
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
            logger.warning("Schedule has %d validation errors:\n%s", len(errors),
                           "\n".join(f"  - {error}" for error in errors[:5]))
        
        return schedule
    
    def _scheduling_priority(self, courses: List[str]) -> List[str]:
        """
        Order courses so the starts of long prerequisite chains are placed first.

        Courses are sorted by the length of the longest chain of required courses
        that depends on them, then by how few terms they're offered in (so a
        Fall-only course isn't crowded out of its one chance), then topologically.
        """
        topo = self.prereq_graph.topological_sort(courses)
        subgraph = self.prereq_graph.graph.subgraph(courses)
        height = {code: 0 for code in courses}
        if nx.is_directed_acyclic_graph(subgraph):
            for code in reversed(topo):
                successors = list(subgraph.successors(code))
                if successors:
                    height[code] = 1 + max(height[s] for s in successors)
        position = {code: i for i, code in enumerate(topo)}

        def terms_offered(code: str) -> int:
            course = self.course_catalog.get(code)
            return len(course.offered) if course else 99

        return sorted(courses, key=lambda c: (-height[c], terms_offered(c), position.get(c, len(position))))
    
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
        completed = student.credited_courses()
        
        # Track cumulative credits earned (starting credits + scheduled credits)
        cumulative_credits = student.credits_completed
        
        # Track which courses haven't been scheduled yet. ``courses`` is in
        # priority order; ``remaining_courses`` is only used for membership.
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
            upper_level_cs_count = 0
            
            # Try each remaining course, in priority order
            for course_code in [c for c in courses if c in remaining_courses]:
                if current_credits >= max_credits:
                    break  # Semester is full
                
                # Skip if equivalent course already completed or scheduled
                if self.course_catalog.has_equivalent_in(course_code, completed):
                    remaining_courses.discard(course_code)
                    continue
                
                # Check if course exists
                if course_code not in self.course_catalog:
                    remaining_courses.remove(course_code)
                    continue
                
                course = self.course_catalog[course_code]
                
                is_upper_cs = rules.counts_toward_upper_level_cmsc_cap(course)
                if is_upper_cs and upper_level_cs_count >= rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER:
                    continue

                if cumulative_credits < rules.credits_required_before(course):
                    continue  # e.g. FSPW needs 60 credits; try a later semester
                
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
                equivalents = self.course_catalog.equivalents(course_code)
                completed.update(equivalents)
                remaining_courses -= equivalents
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
    
    def audit(self, student_program: StudentDegreeProgram,
              schedule: Optional[Schedule] = None) -> AuditReport:
        """
        Audit every requirement of ``student_program`` against the courses in
        ``schedule`` plus those the student already has credit for. Without a
        schedule this reports the student's current progress.
        """
        student = student_program.student
        courses = student.credited_courses() | set(schedule.get_all_courses() if schedule else ())
        return audit_requirements(courses, student_program.get_all_requirements(),
                                  self.course_catalog,
                                  prior_credits=prior_credits(student, self.course_catalog))
