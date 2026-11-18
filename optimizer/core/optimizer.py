"""Main schedule optimization engine."""

from collections import Counter
from typing import Dict, List, Mapping, Set, Optional
import networkx as nx
from ..models.catalog import Catalog
from ..models.course import Course
from ..models.schedule import Schedule, Semester, SemesterType
from ..models.student import StudentProfile, StudentDegreeProgram
from ..models.requirements import Requirement, RequirementType
from .graph import PrerequisiteGraph
from .constraints import ConstraintValidator
from . import rules


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
        
        # Phase 3: Order courses (long prerequisite chains first, then topological)
        ordered_courses = self._scheduling_priority(remaining_courses)
        
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
        """
        Choose the courses that satisfy every requirement, in a deterministic order.

        COURSE/GROUP/CHOICE requirements each claim their own courses (a course
        counts toward only one of them). GEN_ED requirements may reuse any
        selected or credited course whose chosen Gen Ed option covers the category.
        """
        requirements = student_program.get_all_requirements()

        # Track which Gen Ed option was selected for each course
        # Format: {course_code: [list of gen_ed categories from selected option]}
        self._gen_ed_course_assignments: Dict[str, List[str]] = {}
        self._selected: Dict[str, None] = {}  # insertion-ordered set
        self._claimed: Set[str] = set()
        self._credited = student_program.student.credited_courses()
        self._mandatory: Set[str] = set()
        for req in requirements:
            self._collect_mandatory(req)

        for req in requirements:
            self._select_for_requirement(req)

        return self.course_catalog.dedupe_equivalents(self._selected)

    def _collect_mandatory(self, requirement: Requirement) -> None:
        """Gather single-course requirements so prerequisite checks can count on them."""
        if requirement.type == RequirementType.COURSE and requirement.course_code:
            self._mandatory.add(requirement.course_code)
        for item in (requirement.courses or []) + (requirement.choices or []):
            if isinstance(item, Requirement):
                self._collect_mandatory(item)

    def _select(self, code: str, claim: bool = True) -> None:
        self._selected[code] = None
        if claim:
            self._claimed.add(code)

    def _have(self, code: str) -> bool:
        return self.course_catalog.has_equivalent_in(code, self._credited)

    def _taken_or_planned(self, code: str) -> bool:
        return self.course_catalog.has_equivalent_in(code, self._credited | set(self._selected))

    def _reachable(self, code: str) -> bool:
        """Whether the course's prerequisites can be met by credited/selected/mandatory courses."""
        course = self.course_catalog.get(code)
        if course is None:
            return False
        available = self._credited | set(self._selected) | self._mandatory
        return course.prerequisites_satisfied({c: "A" for c in available})

    def _select_for_requirement(self, requirement: Requirement) -> None:
        rtype = requirement.type

        if rtype == RequirementType.COURSE:
            if requirement.course_code:
                self._select(requirement.course_code)

        elif rtype == RequirementType.CHOICE:
            choices = requirement.choices or []
            codes = [c for c in choices if isinstance(c, str)]
            if codes:
                self._pick_from_group(codes, min_courses=1)
            else:
                nested = [c for c in choices if isinstance(c, Requirement)]
                if nested:
                    self._select_for_requirement(nested[0])

        elif rtype == RequirementType.GROUP:
            items = requirement.courses or []
            for item in items:
                if isinstance(item, Requirement):
                    self._select_for_requirement(item)
            codes = [c for c in items if isinstance(c, str)]
            if requirement.min_courses is None and not requirement.min_credits:
                for code in codes:  # no quantity given: every listed course is required
                    self._select(code)
            else:
                self._pick_from_group(
                    codes,
                    min_courses=requirement.min_courses or 0,
                    min_credits=requirement.min_credits or 0,
                    min_areas=requirement.min_areas or 0,
                    max_per_area=requirement.max_from_same_area,
                )

        elif rtype == RequirementType.GEN_ED:
            if requirement.gen_ed_category:
                self._select_gen_ed(requirement)

    def _pick_from_group(self, codes: List[str], min_courses: int = 0, min_credits: int = 0,
                         min_areas: int = 0, max_per_area: Optional[int] = None) -> None:
        """
        Pick courses from ``codes`` until the count/credit/area minimums are met.

        Preference order: courses already credited, then courses whose
        prerequisites are reachable, then courses from a not-yet-covered area
        (while ``min_areas`` is unmet), then the order the requirement lists them.
        """
        candidates = list(dict.fromkeys(
            c for c in codes if c in self.course_catalog and c not in self._claimed
        ))
        picked: List[str] = []
        credits = 0
        area_counts: Counter = Counter()

        def satisfied() -> bool:
            return (len(picked) >= min_courses and credits >= min_credits
                    and len(area_counts) >= min_areas)

        while not satisfied():
            best, best_key = None, None
            for index, code in enumerate(candidates):
                if code in picked or (self._taken_or_planned(code) and not self._have(code)):
                    continue  # already planned via another requirement or an equivalent
                area = self.course_catalog.primary_area(code)
                if max_per_area is not None and area and area_counts[area] >= max_per_area:
                    continue
                needs_area = len(area_counts) < min_areas
                key = (
                    not self._have(code),
                    not self._reachable(code),
                    not (needs_area and area is not None and area not in area_counts),
                    index,
                )
                if best_key is None or key < best_key:
                    best, best_key = code, key
            if best is None:
                break  # not enough eligible courses to satisfy the requirement
            picked.append(best)
            credits += self.course_catalog[best].credits
            area = self.course_catalog.primary_area(best)
            if area:
                area_counts[area] += 1
            self._select(best)

    def _gen_ed_option(self, code: str, category: str) -> Optional[List[str]]:
        """The course's Gen Ed option covering ``category`` (directly or via an equivalent category)."""
        course = self.course_catalog.get(code)
        if course is None:
            return None
        for satisfying in rules.gen_ed_categories_satisfying(category):
            option = course.get_gen_ed_option_for_category(satisfying)
            if option is not None:
                return option
        return None

    def _counts_toward(self, code: str, category: str) -> bool:
        """Whether a credited/selected course can count toward ``category``, locking its option."""
        assigned = self._gen_ed_course_assignments.get(code)
        if assigned is not None:
            return any(c in assigned for c in rules.gen_ed_categories_satisfying(category))
        option = self._gen_ed_option(code, category)
        if option is None:
            return False
        self._gen_ed_course_assignments[code] = option
        return True

    def _select_gen_ed(self, requirement: Requirement) -> None:
        category = requirement.gen_ed_category
        min_courses = requirement.min_courses or 1
        min_credits = requirement.min_credits or 0
        target_credits = min_credits / min_courses if min_credits else 3

        count, credits = 0, 0

        def satisfied() -> bool:
            return count >= min_courses and credits >= min_credits

        for code in dict.fromkeys(sorted(self._credited) + list(self._selected)):
            if satisfied():
                return
            if code in self.course_catalog and self._counts_toward(code, category):
                count += 1
                credits += self.course_catalog[code].credits

        if satisfied():
            return

        candidates = []
        for code in sorted(self.course_catalog):
            course = self.course_catalog[code]
            if (course.credits <= 0 or not course.offered
                    or code in self._gen_ed_course_assignments
                    or self._taken_or_planned(code)
                    or self._gen_ed_option(code, category) is None):
                continue
            key = (
                bool(course.restrictions),
                not self._reachable(code),
                abs(course.credits - target_credits),
                code,
            )
            candidates.append((key, code))
        candidates.sort()

        for _, code in candidates:
            if satisfied():
                break
            if self._taken_or_planned(code):
                continue  # an equivalent was picked earlier in this loop
            self._gen_ed_course_assignments[code] = self._gen_ed_option(code, category)
            self._select(code, claim=False)
            count += 1
            credits += self.course_catalog[code].credits

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
    
    def validate_current_progress(self, student_program: StudentDegreeProgram) -> Dict:
        """
        Validate student's current progress against requirements.
        
        Returns:
            Dictionary with progress information
        """
        student = student_program.student
        completed = student.credited_courses()
        
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
