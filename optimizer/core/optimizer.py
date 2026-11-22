"""Main schedule optimization engine."""

import logging
import math
from typing import Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import networkx as nx
from ..models.catalog import Catalog
from ..models.course import Course, PrerequisiteCondition, PrerequisiteType
from ..models.schedule import TERM_ORDER, Schedule, Semester, SemesterType
from ..models.student import StudentProfile, StudentDegreeProgram
from .balance import balance_credits
from .solver import solve_schedule
from .graph import PrerequisiteGraph
from .constraints import ConstraintValidator
from .audit import (AuditReport, RequirementResult, audit_benchmarks, audit_requests,
                    audit_requirements)
from .categories import prior_credits
from .selection import CourseSelector, Selection
from . import rules

logger = logging.getLogger(__name__)


REGULAR_SEMESTERS = 8  # Fall/Spring semesters in a 4-year plan


def _finish(schedule: Schedule) -> Tuple[int, int]:
    """When ``schedule``'s last term is, for comparing graduation dates."""
    if not schedule.semesters:
        return (0, 0)
    last = schedule.semesters[-1]
    return (last.year, TERM_ORDER.index(last.type))


def plan_terms(student: StudentProfile, start_year: int,
               start_semester: SemesterType) -> List[Tuple[int, SemesterType]]:
    """
    The terms of a plan, in order: ``REGULAR_SEMESTERS`` Fall/Spring
    semesters from ``start_semester``, with a Winter term between each Fall
    and the next Spring (``include_winter``; Winter Y+1 follows Fall Y) and a
    Summer between each Spring and the next Fall (``include_summer``).
    """
    terms: List[Tuple[int, SemesterType]] = []
    year, term = start_year, start_semester
    for i in range(REGULAR_SEMESTERS):
        terms.append((year, term))
        if i == REGULAR_SEMESTERS - 1:
            break
        if term == SemesterType.FALL:
            year += 1  # Spring (and Winter) come in the next calendar year
            if student.include_winter:
                terms.append((year, SemesterType.WINTER))
            term = SemesterType.SPRING
        else:
            if student.include_summer:
                terms.append((year, SemesterType.SUMMER))
            term = SemesterType.FALL
    return terms


class ScheduleOptimizer:
    """Optimizes course schedules for students."""
    
    def __init__(self, course_catalog: Mapping[str, Course], use_solver: bool = True):
        """
        Initialize the optimizer.
        
        Args:
            course_catalog: All available courses (a ``Catalog`` or a plain dict)
            use_solver: Improve the greedy schedule with the CP-SAT solver
                (``solver.solve_schedule``) when OR-Tools is installed
        """
        self.course_catalog = Catalog.of(course_catalog)
        self.use_solver = use_solver
        self.prereq_graph = PrerequisiteGraph(self.course_catalog)
        self.validator = ConstraintValidator(self.course_catalog)
        self.selector = CourseSelector(self.course_catalog)

    def for_program(self, student_program: StudentDegreeProgram) -> 'ScheduleOptimizer':
        """
        An optimizer whose catalog has the program's own prerequisites
        (``StudentDegreeProgram.prerequisite_overrides``: RAS students take
        CMSC477 after ENEE467), or ``self`` if the program has none. The public
        methods plan and audit with it.
        """
        catalog = self.course_catalog.with_prerequisites(student_program.prerequisite_overrides())
        return (self if catalog is self.course_catalog
                else ScheduleOptimizer(catalog, use_solver=self.use_solver))

    def select_courses(self, student_program: StudentDegreeProgram) -> Selection:
        """The courses chosen to satisfy the program's requirements (pipeline phase 1)."""
        return self.for_program(student_program).selector.select(student_program)
    
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
        return self.for_program(student_program)._plans(student_program, start_year,
                                                        start_semester, 1)[0]

    def generate_multiple_scenarios(self, student_program: StudentDegreeProgram,
                                    n_scenarios: int = 3, min_changes: int = 4,
                                    start_year: int = 2025,
                                    start_semester: SemesterType = SemesterType.FALL
                                    ) -> List[Schedule]:
        """
        Up to ``n_scenarios`` different plans, best first: the plan
        ``optimize_schedule`` returns, then the solver's best plans that put
        at least ``min_changes`` courses in a different term than every
        earlier plan. Every plan takes the same courses, places and meets on
        time as many as the first, and graduates no later. Fewer come back when no such plan
        exists, or only the first without OR-Tools or with ``use_solver`` off.
        """
        return self.for_program(student_program)._plans(student_program, start_year,
                                                        start_semester, n_scenarios, min_changes)

    def _plans(self, student_program: StudentDegreeProgram, start_year: int,
               start_semester: SemesterType, count: int, min_changes: int = 4) -> List[Schedule]:
        selection = self.selector.select(student_program)
        required_courses = selection.courses
        
        student = student_program.student
        # Credited courses drop out, unless a minimum grade means taking them again
        retakes = set(selection.retakes)
        remaining_courses = [c for c in required_courses
                             if not student.has_completed(c) or c in retakes]
        
        # Free electives go last, so they only fill room required courses leave.
        # Benchmarks and requested courses' deadlines come first.
        deadlines = self._benchmark_deadlines(student_program, required_courses)
        for code, credits in self._request_deadlines(student).items():
            deadlines[code] = min(credits, deadlines.get(code, credits))
        ordered_courses = self._scheduling_priority(remaining_courses, deadlines, student)
        # Requests no requirement counts and with no deadline come after the
        # required courses, before free electives
        counted = {c for codes in selection.by_requirement.values() for c in codes}
        optional = {c for c in selection.requested if c not in counted and c not in deadlines}
        electives = set(selection.electives)
        ordered_courses.sort(key=lambda c: 2 if c in electives else 1 if c in optional else 0)
        
        schedule = self._assign_courses_to_semesters(
            ordered_courses,
            student,
            start_year,
            start_semester,
            retakes,
        )
        # Even out the loads without losing a benchmark or request deadline the plan meets
        met = self._deadlines_met(student_program, schedule)
        balance_credits(schedule, self.course_catalog, student, movable_first=electives,
                        keeps=lambda s: self._deadlines_met(student_program, s) >= met)
        plans = [schedule]
        if self.use_solver:
            solve = lambda avoid=(): self._solve(student_program, remaining_courses,  # noqa: E731
                                                 electives | optional, start_year, start_semester,
                                                 hint=schedule, avoid=avoid, min_changes=min_changes)
            solved = solve()
            if solved is not None and self._no_worse(student_program, solved, schedule):
                plans = [solved]
            while len(plans) < count:
                alternative = solve(avoid=plans)
                if (alternative is None
                        or not self._no_worse(student_program, alternative, plans[0])
                        or _finish(alternative) > _finish(plans[0])):
                    break  # no other plan as good that graduates as early
                plans.append(alternative)
        schedule = plans[0]
        
        is_valid, errors = self.validator.validate_schedule(
            schedule,
            student,
            student.preferred_credit_load[0],
            student.preferred_credit_load[1]
        )
        
        if not is_valid:
            logger.warning("Schedule has %d validation errors:\n%s", len(errors),
                           "\n".join(f"  - {error}" for error in errors[:5]))

        for result in (self._audit_benchmarks(student_program, schedule)
                       + self._audit_requests(student_program, schedule)):
            if not result.satisfied:
                logger.warning("%s missed: %s", result.requirement.name, result.reason)
        
        return plans

    def _no_worse(self, student_program: StudentDegreeProgram, plan: Schedule,
                  reference: Schedule) -> bool:
        """Whether ``plan`` places as many courses and meets every deadline ``reference`` meets."""
        return (len(plan.get_all_courses()) >= len(reference.get_all_courses())
                and self._deadlines_met(student_program, plan)
                >= self._deadlines_met(student_program, reference))

    def _solve(self, student_program: StudentDegreeProgram, courses: List[str],
               electives: Set[str], start_year: int, start_semester: SemesterType,
               hint: Schedule, avoid: Sequence[Schedule] = (),
               min_changes: int = 4) -> Optional[Schedule]:
        """
        The CP-SAT schedule (``solver.solve_schedule``, hinted with ``hint``,
        at least ``min_changes`` placements away from each plan in ``avoid``),
        or None if the solver finds none.
        """
        student = student_program.student
        credit_deadlines = self._benchmark_deadlines(student_program, courses)
        semester_deadlines: Dict[str, int] = {}
        for request in student.requested_courses:
            if request.by_credits is not None:
                credit_deadlines[request.code] = min(
                    request.by_credits, credit_deadlines.get(request.code, request.by_credits))
            if request.by_semester is not None:
                semester_deadlines[request.code] = min(
                    request.by_semester, semester_deadlines.get(request.code, request.by_semester))
        return solve_schedule(courses, self.course_catalog, student,
                              plan_terms(student, start_year, start_semester),
                              electives=electives, credit_deadlines=credit_deadlines,
                              semester_deadlines=semester_deadlines, hint=hint,
                              avoid=avoid, min_changes=min_changes)

    def _deadlines_met(self, student_program: StudentDegreeProgram, schedule: Schedule) -> Set[str]:
        """Ids of the benchmarks and requested courses ``schedule`` meets on time."""
        return {r.requirement.id for r in (self._audit_benchmarks(student_program, schedule)
                                           + self._audit_requests(student_program, schedule))
                if r.satisfied}

    def _benchmark_deadlines(self, student_program: StudentDegreeProgram,
                             courses: List[str]) -> Dict[str, int]:
        """
        Selected course -> the credits of the earliest benchmark it counts
        toward. A benchmark's courses are the ones the audit applies to it from
        the selection plus credited courses.
        """
        available = list(courses) + sorted(student_program.student.credited_courses())
        deadlines: Dict[str, int] = {}
        for credits, requirement in student_program.benchmark_requirements():
            result = audit_requirements(available, [requirement], self.course_catalog)
            for code in result[requirement.id].applied:
                deadlines.setdefault(code, credits)
        return deadlines
    
    def _request_deadlines(self, student: StudentProfile) -> Dict[str, int]:
        """
        Requested course -> its deadline in cumulative credits, for ordering
        alongside benchmarks. A ``by_semester`` deadline N counts as the credits
        N semesters at the minimum preferred load would reach.
        """
        deadlines: Dict[str, int] = {}
        for request in student.requested_courses:
            candidates = [request.by_credits] if request.by_credits is not None else []
            if request.by_semester is not None:
                candidates.append(student.credits_completed
                                  + request.by_semester * student.preferred_credit_load[0])
            if request.code in deadlines:
                candidates.append(deadlines[request.code])  # requested twice
            if candidates:
                deadlines[request.code] = min(candidates)
        return deadlines

    def _scheduling_priority(self, courses: List[str],
                             deadlines: Optional[Dict[str, int]] = None,
                             student: Optional[StudentProfile] = None) -> List[str]:
        """
        Order courses so benchmark courses and the starts of long prerequisite
        chains are placed first.

        Courses are sorted by their benchmark deadline in credits (a course
        inherits the earliest deadline of any required course that depends on
        it; none sorts last), then by the length of the longest chain of
        required courses that depends on them, then by how few terms they're
        offered in among the plan's terms (``rules.terms_offered``, so a
        Fall-only course isn't crowded out of its one chance), then
        topologically.
        """
        deadlines = deadlines or {}
        topo = self.prereq_graph.topological_sort(courses)
        subgraph = self.prereq_graph.graph.subgraph(courses)
        height = {code: 0 for code in courses}
        due = {code: deadlines.get(code, math.inf) for code in courses}
        if nx.is_directed_acyclic_graph(subgraph):
            for code in reversed(topo):
                successors = list(subgraph.successors(code))
                if successors:
                    height[code] = 1 + max(height[s] for s in successors)
                    due[code] = min(due[code], *(due[s] for s in successors))
        position = {code: i for i, code in enumerate(topo)}

        student = student or StudentProfile(student_id="", name="", primary_major="")

        def terms_offered(code: str) -> int:
            course = self.course_catalog.get(code)
            return len(rules.terms_offered(course, student)) if course else 99

        return sorted(courses, key=lambda c: (due[c], -height[c], terms_offered(c),
                                              position.get(c, len(position))))
    
    def _assign_courses_to_semesters(self, courses: List[str],
                                    student: StudentProfile,
                                    start_year: int,
                                    start_semester: SemesterType,
                                    retakes: Collection[str] = ()) -> Schedule:
        """
        Assign courses to semesters using a greedy algorithm (``solver``
        improves on it). Prerequisites are checked against the student's
        grades for credited courses; placed courses count as an A, and
        ``retakes`` are scheduled even though they are credited.
        """
        schedule = Schedule()
        completed: Dict[str, str] = student.grades()
        
        cumulative_credits = student.credits_completed
        
        # Track which courses haven't been scheduled yet. ``courses`` is in
        # priority order; ``remaining_courses`` is only used for membership.
        remaining_courses = set(courses)
        
        for year, sem_type in plan_terms(student, start_year, start_semester):
            if not remaining_courses:
                break  # All courses scheduled
                
            semester = Semester(year=year, type=sem_type)
            
            min_credits, max_credits = rules.credit_load(student, sem_type.value)
            max_courses = rules.course_limit(student, sem_type.value)
            current_credits = 0
            courses_added_this_semester = []
            upper_level_cs_count = 0
            
            for course_code in [c for c in courses if c in remaining_courses]:
                if current_credits >= max_credits or (
                        max_courses is not None and len(courses_added_this_semester) >= max_courses):
                    break  # Semester is full
                
                if (course_code not in retakes
                        and self.course_catalog.has_equivalent_in(course_code, completed)):
                    remaining_courses.discard(course_code)
                    continue
                
                if course_code not in self.course_catalog:
                    remaining_courses.remove(course_code)
                    continue
                
                if self.course_catalog.has_equivalent_in(course_code, courses_added_this_semester):
                    continue  # placed with a course it is a corequisite of

                if not self._takeable(course_code, sem_type, completed, cumulative_credits):
                    continue  # prerequisites, offering or credit rules: try a later semester

                # Corequisites: met by earlier courses or this semester's, else
                # take the planned courses that meet them now, together with it
                concurrent = {**completed, **{e: "A" for c in courses_added_this_semester + [course_code]
                                              for e in self.course_catalog.equivalents(c)}}
                bundle = self._corequisite_bundle(
                    course_code, concurrent,
                    [c for c in courses if c in remaining_courses
                     and c not in courses_added_this_semester and c != course_code],
                    sem_type, completed, cumulative_credits)
                if bundle is None:
                    continue

                group = [course_code] + bundle
                credits = sum(self.course_catalog[c].credits for c in group)
                upper_cs = sum(rules.counts_toward_upper_level_cmsc_cap(self.course_catalog[c])
                               for c in group)
                if (upper_cs and upper_level_cs_count + upper_cs > rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER):
                    continue
                if max_courses is not None and len(courses_added_this_semester) + len(group) > max_courses:
                    continue
                if current_credits + credits <= max_credits:
                    for code in group:
                        semester.add_course(code)
                        courses_added_this_semester.append(code)
                    current_credits += credits
                    upper_level_cs_count += upper_cs
            
            for course_code in courses_added_this_semester:
                equivalents = self.course_catalog.equivalents(course_code)
                completed.update({e: "A" for e in equivalents})
                remaining_courses -= equivalents
                if course_code in self.course_catalog:
                    cumulative_credits += self.course_catalog[course_code].credits
            
            if semester.courses:
                schedule.add_semester(semester)
        
        return schedule
    
    def _takeable(self, code: str, sem_type: SemesterType, completed: Mapping[str, str],
                  cumulative_credits: int) -> bool:
        """
        Whether ``code`` can be taken in a ``sem_type`` semester after
        ``completed`` and ``cumulative_credits``: prerequisites met, offered,
        and ``rules.credits_required_before`` (FSPW at 60 credits) reached.
        """
        course = self.course_catalog[code]
        return (cumulative_credits >= rules.credits_required_before(course)
                and self.validator.check_prerequisites(code, completed)[0]
                and self.validator.check_availability(code, sem_type.value))

    def _corequisite_bundle(self, code: str, concurrent: Mapping[str, str], candidates: List[str],
                            sem_type: SemesterType, completed: Mapping[str, str],
                            cumulative_credits: int) -> Optional[List[str]]:
        """
        The planned courses (from ``candidates``, in priority order) to take
        in the same semester as ``code`` so its corequisites are met, given
        the ``concurrent`` courses (code -> grade: completed, this semester's
        and ``code``, with equivalents): [] if they already are, None if they
        can't be now.
        Each added course must be takeable this semester and have its own
        corequisites met by the result (PHYS270 and PHYS271 need each other).
        """
        catalog = self.course_catalog

        def needed(condition: PrerequisiteCondition) -> Optional[List[str]]:
            if condition.is_satisfied(concurrent):
                return []
            if condition.type == PrerequisiteType.AND:
                parts = [needed(c) for c in condition.conditions or []]
                return None if None in parts else [c for part in parts for c in part]
            options = [c for c in candidates if c in (condition.courses or [])
                       and self._takeable(c, sem_type, completed, cumulative_credits)]
            if condition.type == PrerequisiteType.COURSE:
                missing = [c for c in condition.courses or []
                           if not PrerequisiteCondition(PrerequisiteType.COURSE, courses=[c],
                                                        min_grade=condition.min_grade
                                                        ).is_satisfied(concurrent)]
                return missing if all(c in options for c in missing) else None
            # OR: the highest-priority planned alternative, else a nested condition
            if options:
                return [options[0]]
            for nested in condition.conditions or []:
                part = needed(nested)
                if part is not None:
                    return part
            return None

        bundle: List[str] = []
        for condition in catalog[code].corequisites:
            part = needed(condition)
            if part is None:
                return None
            bundle += [c for c in part if c not in bundle]
        together = {**concurrent, **{e: "A" for c in bundle for e in catalog.equivalents(c)}}
        if all(catalog[c].corequisites_satisfied(together) for c in bundle):
            return bundle
        return None

    def audit(self, student_program: StudentDegreeProgram,
              schedule: Optional[Schedule] = None) -> AuditReport:
        """
        Audit every requirement of ``student_program`` against the courses in
        ``schedule`` plus those the student already has credit for, followed by
        the majors' benchmarks (``audit_benchmarks``). Without a schedule this
        reports the student's current progress. The student's requested
        courses (``audit_requests``) come last.
        """
        return self.for_program(student_program)._audit(student_program, schedule)

    def _audit(self, student_program: StudentDegreeProgram,
               schedule: Optional[Schedule]) -> AuditReport:
        student = student_program.student
        courses = student.credited_courses() | set(schedule.get_all_courses() if schedule else ())
        owned = student_program.owned_requirements()
        # A course taken again in the plan counts at its planned grade, not the old one
        planned = set(schedule.get_all_courses() if schedule else ())
        grades = {c: g for c, g in student.grades().items() if c not in planned}
        report = audit_requirements(courses, [r for _, r in owned], self.course_catalog,
                                    prior_credits=prior_credits(student, self.course_catalog),
                                    owners=[o for o, _ in owned], grades=grades)
        return AuditReport(report.results
                           + tuple(self._audit_benchmarks(student_program, schedule))
                           + tuple(self._audit_requests(student_program, schedule)))

    def _audit_requests(self, student_program: StudentDegreeProgram,
                        schedule: Optional[Schedule]) -> List[RequirementResult]:
        student = student_program.student
        return audit_requests(student.requested_courses,
                              schedule.semesters if schedule else (), self.course_catalog,
                              credited=sorted(student.credited_courses()),
                              credits_completed=student.credits_completed)

    def _audit_benchmarks(self, student_program: StudentDegreeProgram,
                          schedule: Optional[Schedule]) -> List[RequirementResult]:
        student = student_program.student
        return audit_benchmarks(student_program.benchmark_requirements(),
                                schedule.semesters if schedule else (), self.course_catalog,
                                credited=sorted(student.credited_courses()),
                                credits_completed=student.credits_completed,
                                grades=student.grades())
