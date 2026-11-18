"""Choose the courses that satisfy a degree program's requirements."""

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Set, Tuple

from ..models.catalog import Catalog
from ..models.course import Course
from ..models.requirements import Requirement, RequirementType
from ..models.student import StudentDegreeProgram
from . import rules
from .categories import category_matches, credit_hours, has_filters, prior_credits
from .gen_eds import GenEdLedger

RequirementPath = Tuple[int, ...]
"""
Where a requirement sits in a program: its index in
``StudentDegreeProgram.get_all_requirements()``, followed by its index in the
parent's ``courses``/``choices`` list for each level of nesting. Unlike ``id``s,
paths can't collide.
"""


@dataclass(frozen=True)
class Selection:
    """The result of one ``CourseSelector.select`` call."""

    courses: Tuple[str, ...]
    """Chosen course codes in selection order, with equivalent duplicates dropped."""

    by_requirement: Mapping[RequirementPath, Tuple[str, ...]]
    """
    Courses each visited requirement took, in walk order: courses it chose plus
    credited or already-chosen courses a gen-ed reused. Codes are as picked,
    before equivalent duplicates are dropped from ``courses``.
    """

    gen_ed_options: Mapping[str, Tuple[str, ...]]
    """The gen-ed option each course is locked to, in the order they were locked."""

    electives: Tuple[str, ...] = ()
    """Free electives: courses picked only to reach a CREDIT_HOURS minimum, in pick order."""


class CourseSelector:
    """Picks courses for a degree program. Holds no per-run state, so it is reentrant."""

    def __init__(self, catalog: Mapping[str, Course]):
        self.catalog = Catalog.of(catalog)

    def select(self, program: StudentDegreeProgram) -> Selection:
        """
        Choose the courses that satisfy every requirement, in a deterministic order.

        COURSE/GROUP/CHOICE requirements each claim their own courses (a course
        counts toward only one of them). GEN_ED requirements may reuse any
        selected or credited course whose chosen Gen Ed option covers the category.
        """
        return _SelectionRun(self.catalog, program).run()


class _SelectionRun:
    """The state of a single ``CourseSelector.select`` call."""

    def __init__(self, catalog: Catalog, program: StudentDegreeProgram):
        self.catalog = catalog
        self.requirements = program.get_all_requirements()
        self.credited = program.student.credited_courses()
        self.selected: Dict[str, None] = {}  # insertion-ordered set
        self.claimed: Set[str] = set()
        self.mandatory: Set[str] = set()
        self.gen_eds = GenEdLedger(catalog)
        self.assigned: Dict[RequirementPath, Dict[str, None]] = {}
        self.prior_credits = prior_credits(program.student, catalog)
        self.credit_minimums: List[Tuple[Requirement, RequirementPath]] = []
        self.electives: Dict[str, None] = {}

    def run(self) -> Selection:
        for req in self.requirements:
            self._collect_mandatory(req)
        for index, req in enumerate(self.requirements):
            self._select_for_requirement(req, (index,))
        # Credit minimums count every course, so they're filled once everything
        # else is picked; the most specific (filtered) ones first, so a course
        # added for "30 upper-level credits" also counts toward "120 total".
        for requirement, path in sorted(self.credit_minimums, key=lambda rp: not has_filters(rp[0])):
            self._select_electives(requirement, path)
        return Selection(
            courses=tuple(self.catalog.dedupe_equivalents(self.selected)),
            by_requirement=MappingProxyType({p: tuple(c) for p, c in self.assigned.items()}),
            gen_ed_options=MappingProxyType(self.gen_eds.locked),
            electives=tuple(self.electives),
        )

    def _collect_mandatory(self, requirement: Requirement) -> None:
        """Gather single-course requirements so prerequisite checks can count on them."""
        if requirement.type == RequirementType.COURSE and requirement.course_code:
            self.mandatory.add(requirement.course_code)
        for item in (requirement.courses or []) + (requirement.choices or []):
            if isinstance(item, Requirement):
                self._collect_mandatory(item)

    def _select(self, code: str, path: RequirementPath, claim: bool = True) -> None:
        self.selected[code] = None
        self.assigned[path][code] = None
        if claim:
            self.claimed.add(code)

    def _have(self, code: str) -> bool:
        return self.catalog.has_equivalent_in(code, self.credited)

    def _taken_or_planned(self, code: str) -> bool:
        return self.catalog.has_equivalent_in(code, self.credited | set(self.selected))

    def _reachable(self, code: str) -> bool:
        """Whether the course's prerequisites can be met by credited/selected/mandatory courses."""
        course = self.catalog.get(code)
        if course is None:
            return False
        available = self.credited | set(self.selected) | self.mandatory
        return course.prerequisites_satisfied({c: "A" for c in available})

    def _select_for_requirement(self, requirement: Requirement, path: RequirementPath) -> None:
        self.assigned[path] = {}
        rtype = requirement.type

        if rtype == RequirementType.COURSE:
            if requirement.course_code:
                self._select(requirement.course_code, path)

        elif rtype == RequirementType.CHOICE:
            choices = requirement.choices or []
            codes = [c for c in choices if isinstance(c, str)]
            if codes:
                self._pick_from_group(codes, path, min_courses=1)
            else:
                nested = [(i, c) for i, c in enumerate(choices) if isinstance(c, Requirement)]
                if nested:
                    index, first = nested[0]
                    self._select_for_requirement(first, path + (index,))

        elif rtype == RequirementType.GROUP:
            items = requirement.courses or []
            for index, item in enumerate(items):
                if isinstance(item, Requirement):
                    self._select_for_requirement(item, path + (index,))
            codes = [c for c in items if isinstance(c, str)]
            if requirement.min_courses is None and not requirement.min_credits:
                for code in codes:  # no quantity given: every listed course is required
                    self._select(code, path)
            else:
                self._pick_from_group(
                    codes, path,
                    min_courses=requirement.min_courses or 0,
                    min_credits=requirement.min_credits or 0,
                    min_areas=requirement.min_areas or 0,
                    max_per_area=requirement.max_from_same_area,
                )

        elif rtype == RequirementType.CATEGORY:
            self._select_category(requirement, path)

        elif rtype == RequirementType.CREDIT_HOURS:
            self.credit_minimums.append((requirement, path))  # filled at the end of run()

        elif rtype == RequirementType.GEN_ED:
            if requirement.gen_ed_category:
                self._select_gen_ed(requirement, path)

    def _pick_from_group(self, codes: List[str], path: RequirementPath, min_courses: int = 0,
                         min_credits: int = 0, min_areas: int = 0,
                         max_per_area: Optional[int] = None) -> None:
        """
        Pick courses from ``codes`` until the count/credit/area minimums are met.

        Preference order: courses already credited, then courses whose
        prerequisites are reachable, then courses from a not-yet-covered area
        (while ``min_areas`` is unmet), then the order the requirement lists them.
        """
        candidates = list(dict.fromkeys(
            c for c in codes if c in self.catalog and c not in self.claimed
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
                area = self.catalog.primary_area(code)
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
            credits += self.catalog[best].credits
            area = self.catalog.primary_area(best)
            if area:
                area_counts[area] += 1
            self._select(best, path)

    def _select_category(self, requirement: Requirement, path: RequirementPath) -> None:
        """
        Pick catalog courses matching a CATEGORY requirement until its minimums are met.

        Courses are preferred in this order: already credited, reachable
        prerequisites, no enrollment restrictions, course code. With
        ``single_department``, each department's best picks are compared and
        the winner is the first that meets the minimums with the fewest
        unreachable, then restricted, picks; then the department with the most
        credited or already-selected courses (the student's prerequisites are
        likely there); then department name.
        """
        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        available = {c: "A" for c in self.credited | set(self.selected) | self.mandatory}

        ranked = []
        for code in sorted(self.catalog):
            course = self.catalog[code]
            if (course.credits <= 0 or not course.offered or code in self.claimed
                    or (self._taken_or_planned(code) and not self._have(code))
                    or not category_matches(requirement, code, self.catalog)):
                continue
            key = (not self._have(code), not course.prerequisites_satisfied(available),
                   bool(course.restrictions), code)
            ranked.append((key, code))
        ranked.sort()

        groups: Dict[str, List[Tuple[tuple, str]]] = {}
        for key, code in ranked:
            department = self.catalog.department(code) if requirement.single_department else ""
            groups.setdefault(department, []).append((key, code))

        def picks_from(candidates: List[Tuple[tuple, str]]) -> Tuple[bool, List[Tuple[tuple, str]]]:
            picked: List[Tuple[tuple, str]] = []
            seen: Set[str] = set()
            credits = 0
            for key, code in candidates:
                if len(picked) >= min_courses and credits >= min_credits:
                    break
                if self.catalog.has_equivalent_in(code, seen):
                    continue  # honors/base or cross-listed twin of a pick
                picked.append((key, code))
                seen.add(code)
                credits += self.catalog[code].credits
            return len(picked) >= min_courses and credits >= min_credits, picked

        planned = [self.catalog.department(c) for c in sorted(self.credited | set(self.selected))]
        best_key, best_picks = None, []
        for department, candidates in groups.items():
            met, picked = picks_from(candidates)
            score = (not met, sum(k[1] for k, _ in picked), sum(k[2] for k, _ in picked),
                     -planned.count(department), department)
            if best_key is None or score < best_key:
                best_key, best_picks = score, picked
        for _, code in best_picks:
            self._select(code, path)

    def _select_electives(self, requirement: Requirement, path: RequirementPath) -> None:
        """
        Add free electives until a CREDIT_HOURS requirement's ``min_credits`` is met.

        Candidates are offered undergraduate courses passing the requirement's
        filters that aren't planned or credited yet. They're preferred in this
        order: no enrollment restrictions, reachable prerequisites, credits
        closest to ``rules.TYPICAL_COURSE_CREDITS``, departments with the most
        planned or credited courses (likely to suit the student), then course code.
        """
        def current_credits() -> int:
            plan = self.catalog.dedupe_equivalents(sorted(self.credited) + list(self.selected))
            return credit_hours(requirement, plan, self.catalog, self.prior_credits)[1]

        credits = current_credits()
        if credits >= requirement.min_credits:
            return

        planned = [self.catalog.department(c) for c in sorted(self.credited | set(self.selected))]
        available = {c: "A" for c in self.credited | set(self.selected) | self.mandatory}
        candidates = []
        for code in sorted(self.catalog):
            course = self.catalog[code]
            if (course.credits <= 0 or not course.offered or not rules.is_undergraduate(course)
                    or self._taken_or_planned(code)
                    or not category_matches(requirement, code, self.catalog)):
                continue
            key = (bool(course.restrictions), not course.prerequisites_satisfied(available),
                   abs(course.credits - rules.TYPICAL_COURSE_CREDITS),
                   -planned.count(self.catalog.department(code)), code)
            candidates.append((key, code))
        candidates.sort()

        for _, code in candidates:
            if credits >= requirement.min_credits:
                break
            if self._taken_or_planned(code):
                continue  # an equivalent was picked earlier in this loop
            self._select(code, path, claim=False)
            self.electives[code] = None
            credits = current_credits()

    def _select_gen_ed(self, requirement: Requirement, path: RequirementPath) -> None:
        category = requirement.gen_ed_category
        min_courses = requirement.min_courses or 1
        min_credits = requirement.min_credits or 0
        target_credits = min_credits / min_courses if min_credits else 3

        count, credits = 0, 0

        def satisfied() -> bool:
            return count >= min_courses and credits >= min_credits

        for code in dict.fromkeys(sorted(self.credited) + list(self.selected)):
            if satisfied():
                return
            if code in self.catalog and self.gen_eds.count(code, category):
                self.assigned[path][code] = None
                count += 1
                credits += self.catalog[code].credits

        if satisfied():
            return

        candidates = []
        for code in sorted(self.catalog):
            course = self.catalog[code]
            if (course.credits <= 0 or not course.offered
                    or code in self.gen_eds.locked
                    or self._taken_or_planned(code)
                    or self.gen_eds.option_for(code, category) is None):
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
            self.gen_eds.count(code, category)
            self._select(code, path, claim=False)
            count += 1
            credits += self.catalog[code].credits
