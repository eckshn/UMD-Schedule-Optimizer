"""
Courses that could take a planned course's place
(``ScheduleOptimizer.course_alternatives``).

An alternative to course X in a schedule is a course Y that can replace X in
the same term, with nothing else in the plan changing:

- Y is an undergraduate catalog course that earns degree credit
  (``rules.is_undergraduate``, ``rules.earns_degree_credit``), offered that
  term. It isn't X or an equivalent of X (honors/base, cross-listed), a course
  the student excluded (``StudentProfile.excluded_courses``), or a course
  already credited or planned, or one sharing credit with one
  (``Catalog.credit_conflicts``).
- Y could count toward every requirement X counts toward in the audit: a
  COURSE/CHOICE/GROUP (benchmarks too) lists it, it passes the CATEGORY or
  filtered CREDIT_HOURS filters, or one of its gen-ed options covers the
  GEN_ED category. Unfiltered credit minimums and DISTRIBUTION accept any
  course, so a free elective's alternatives are every course that fits.
- The swapped schedule stays valid (``balance.schedule_valid``: Y's
  prerequisites and corequisites, and those of every course that relied on
  X, term loads and the ``rules.py`` limits), the term gets no harder than
  the student's maximum or than it was, and the audit (requirements,
  benchmarks and requested courses) still meets everything it met.

Courses a requirement names outright have no alternatives. Rearranging other
courses could open up more alternatives (Y offered only in another term, or
needing another prerequisite); to plan around a course instead, exclude it
and request the one wanted (``excluded_courses``, ``requested_courses``).
"""

import copy
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from ..models.catalog import Catalog
from ..models.requirements import Requirement, RequirementType
from ..models.schedule import Schedule
from ..models.student import StudentProfile
from . import rules
from .audit import AuditReport
from .balance import schedule_valid
from .categories import category_matches, has_filters
from .gen_eds import GenEdLedger


def find_alternatives(schedule: Schedule, catalog: Catalog, student: StudentProfile,
                      audit: Callable[[Schedule], AuditReport],
                      courses: Optional[Iterable[str]] = None) -> Dict[str, Tuple[str, ...]]:
    """
    For each of ``courses`` (default: every course in ``schedule``, in plan
    order), the courses that could replace it in its term (see the module
    docstring), unrestricted ones first, then by code. ``audit`` audits a
    schedule for the student's program. Raises ``ValueError`` for a course
    that isn't in the schedule.
    """
    report = audit(schedule)
    planned = schedule.get_all_courses()
    wanted = planned if courses is None else list(courses)
    missing = [c for c in wanted if c not in planned]
    if missing:
        raise ValueError(f"not in the schedule: {', '.join(missing)}")
    search = _Search(schedule, catalog, student, audit, report)
    return {code: search.alternatives(code) for code in wanted}


class _Search:
    def __init__(self, schedule: Schedule, catalog: Catalog, student: StudentProfile,
                 audit: Callable[[Schedule], AuditReport], report: AuditReport):
        self.schedule = copy.deepcopy(schedule)  # swaps happen here, then are undone
        self.catalog = catalog
        self.student = student
        self.audit = audit
        self.report = report
        self.credited = student.credited_courses()
        self.excluded = set(student.excluded_courses)
        self.accepted: Dict[int, Optional[Set[str]]] = {}  # id(requirement) -> _accepts

    def alternatives(self, code: str) -> Tuple[str, ...]:
        index = next(i for i, s in enumerate(self.schedule.semesters) if code in s.courses)
        semester = self.schedule.semesters[index]
        # What the courses before this term give for prerequisites (Y's own are checked
        # here first, as a cheap filter; schedule_valid checks everything)
        before = dict(self.student.grades())
        for earlier in self.schedule.semesters[:index]:
            before.update({e: "A" for c in earlier.courses for e in self.catalog.equivalents(c)})
        taken = (self.credited | set(self.schedule.get_all_courses())) - {code}
        peak = max(self.student.max_difficulty_per_semester,
                   semester.total_difficulty(self.catalog))
        met = [r.satisfied for r in self.report.results]
        pool = self._pool(code)

        found: List[Tuple[bool, str]] = []
        for other in sorted(pool if pool is not None else self.catalog):
            course = self.catalog.get(other)
            if (course is None or course.credits <= 0
                    or not rules.is_undergraduate(course) or not rules.earns_degree_credit(course)
                    or not course.is_available(semester.type.value)
                    or self.catalog.has_equivalent_in(other, self.excluded | {code})
                    or self.catalog.has_equivalent_in(other, taken)
                    or self.catalog.has_credit_conflict_in(other, taken)
                    or not course.prerequisites_satisfied(before)):
                continue
            position = semester.courses.index(code)
            semester.courses[position] = other
            try:
                if (semester.total_difficulty(self.catalog) <= peak
                        and schedule_valid(self.schedule, self.catalog, self.student)
                        and all(r.satisfied or not was for r, was
                                in zip(self.audit(self.schedule).results, met))):
                    found.append((bool(course.restrictions), other))
            finally:
                semester.courses[position] = code
        return tuple(other for _, other in sorted(found))

    def _pool(self, code: str) -> Optional[Set[str]]:
        """
        The courses every requirement that counts ``code`` would accept in its
        place (equivalents included), or None if they all accept any course.
        """
        pool: Optional[Set[str]] = None
        for result in self.report.results:
            if not result.satisfied or not self.catalog.has_equivalent_in(code, result.applied):
                continue
            key = id(result.requirement)
            if key not in self.accepted:
                self.accepted[key] = self._accepts(result.requirement)
            accepts = self.accepted[key]
            if accepts is not None:
                pool = set(accepts) if pool is None else pool & accepts
        return pool

    def _accepts(self, requirement: Requirement) -> Optional[Set[str]]:
        """The courses ``requirement`` could count, with equivalents; None for any course."""
        rtype = requirement.type
        if rtype in (RequirementType.CATEGORY, RequirementType.CREDIT_HOURS):
            if rtype == RequirementType.CREDIT_HOURS and not has_filters(requirement):
                return None
            return {c for c in self.catalog if category_matches(requirement, c, self.catalog)}
        if rtype == RequirementType.GEN_ED:
            ledger = GenEdLedger(self.catalog)
            category = requirement.gen_ed_category or ""
            return {c for c in self.catalog if ledger.option_for(c, category) is not None}
        if rtype == RequirementType.DISTRIBUTION:
            return None
        codes: Set[str] = {requirement.course_code} if requirement.course_code else set()
        for item in (requirement.courses or []) + (requirement.choices or []):
            if isinstance(item, Requirement):
                nested = self._accepts(item)
                if nested is None:
                    return None
                codes |= nested
            else:
                codes.add(item)
        return {e for c in codes if c in self.catalog for e in self.catalog.equivalents(c)} | codes
