"""Choose the courses that satisfy a degree program's requirements."""

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, Iterator, List, Mapping, Optional, Set, Tuple

from ..models.catalog import Catalog
from ..models.course import Course
from ..models.requirements import Requirement, RequirementType
from ..models.student import DEGREE, StudentDegreeProgram
from . import rules
from .claims import ClaimLedger
from .categories import category_matches, credit_hours, has_filters, prior_credits, within_limits
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

        COURSE/GROUP/CHOICE/CATEGORY requirements each claim their own courses
        (a course counts toward only one of them), except that a requirement
        with ``exclusive`` false leaves its picks for later requirements to
        reuse. GEN_ED requirements may reuse any selected or credited course
        whose chosen Gen Ed option covers the category.
        """
        return _SelectionRun(self.catalog, program).run()


class _SelectionRun:
    """The state of a single ``CourseSelector.select`` call."""

    def __init__(self, catalog: Catalog, program: StudentDegreeProgram):
        self.catalog = catalog
        self.owned = program.owned_requirements()
        self.requirements = [requirement for _, requirement in self.owned]
        self.owner = DEGREE  # the program of the requirement being filled
        self.credited = program.student.credited_courses()
        self.selected: Dict[str, None] = {}  # insertion-ordered set
        self.claims = ClaimLedger(catalog)
        self.shared: Set[str] = set()  # picked by a non-exclusive requirement, not claimed yet
        self.mandatory: Set[str] = set()
        self.gen_eds = GenEdLedger(catalog)
        self.assigned: Dict[RequirementPath, Dict[str, None]] = {}
        self.prior_credits = prior_credits(program.student, catalog)
        self.credit_minimums: List[Tuple[Requirement, RequirementPath]] = []
        self.electives: Dict[str, None] = {}
        # Codes listed by requirements after each top-level index, in total and
        # per program kind ("major", "minor", ...).
        self.listed_after: List[Set[str]] = []
        self.listed_after_by_kind: List[Dict[str, Set[str]]] = []
        later: Set[str] = set()
        later_by_kind: Dict[str, Set[str]] = {}
        for owner, req in reversed(self.owned):
            self.listed_after.append(set(later))
            self.listed_after_by_kind.append({k: set(v) for k, v in later_by_kind.items()})
            later.update(_listed(req))
            later_by_kind.setdefault(owner.kind, set()).update(_listed(req))
        self.listed_after.reverse()
        self.listed_after_by_kind.reverse()

    def run(self) -> Selection:
        for req in self.requirements:
            self._collect_mandatory(req)
        for index, (owner, req) in enumerate(self.owned):
            self.owner = owner
            self._select_for_requirement(req, (index,))
        self.owner = DEGREE
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

    def _select(self, code: str, path: RequirementPath, claim: bool = True,
                shared: bool = False) -> None:
        """
        Add ``code`` to the plan for the requirement at ``path``. It is claimed
        for the current program (no other requirement may pick it, except a
        minor sharing it within the overlap limit, see ``ClaimLedger``) unless
        ``claim`` is false or it is ``shared``: picked by a non-exclusive
        requirement, so a later requirement may still claim it.
        """
        self.selected[code] = None
        self.assigned[path][code] = None
        if shared:
            self.shared.add(code)
        elif claim:
            self.claims.claim(code, self.owner)
            self.shared.discard(code)

    def _have(self, code: str) -> bool:
        return self.catalog.has_equivalent_in(code, self.credited)

    def _taken_or_planned(self, code: str) -> bool:
        return self.catalog.has_equivalent_in(code, self.credited | set(self.selected))

    def _free(self, code: str) -> bool:
        """
        Whether using the course adds nothing to the plan: credited, shared and
        unclaimed, or a major's course the current minor may share.
        """
        return (self._have(code) or self.catalog.has_equivalent_in(code, self.shared)
                or (self.claims.is_overlap(code, self.owner)
                    and self.claims.can_claim(code, self.owner)))

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
        shared = not requirement.exclusive

        if rtype == RequirementType.COURSE:
            if requirement.course_code:
                self._select(requirement.course_code, path, shared=shared)

        elif rtype == RequirementType.CHOICE:
            choices = requirement.choices or []
            codes = [c for c in choices if isinstance(c, str)]
            if codes:
                self._pick_from_group(codes, path, min_courses=1, shared=shared)
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
                    self._select(code, path, shared=shared)
            else:
                self._pick_from_group(
                    codes, path,
                    min_courses=requirement.min_courses or 0,
                    min_credits=requirement.min_credits or 0,
                    min_areas=requirement.min_areas or 0,
                    max_per_area=requirement.max_from_same_area,
                    shared=shared,
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
                         max_per_area: Optional[int] = None, shared: bool = False) -> None:
        """
        Pick courses from ``codes`` until the count/credit/area minimums are met.

        Preference order: courses already credited (or picked by a
        non-exclusive requirement, which this one may reuse), then a major's
        course this minor may share, then courses whose prerequisites are reachable,
        then courses from a not-yet-covered area (while ``min_areas`` is unmet),
        then courses a later program that may share this one's courses lists
        (``rules.may_share``: a minor after a major), then the order the
        requirement lists them.
        """
        shareable = self._shareable_later(path)
        candidates = list(dict.fromkeys(
            c for c in codes if c in self.catalog and self.claims.can_claim(c, self.owner)
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
                if code in picked or (self._taken_or_planned(code) and not self._free(code)):
                    continue  # already planned via another requirement or an equivalent
                area = self.catalog.primary_area(code)
                if max_per_area is not None and area and area_counts[area] >= max_per_area:
                    continue
                needs_area = len(area_counts) < min_areas
                key = (
                    not self._free(code),
                    self.claims.is_overlap(code, self.owner),
                    not self._reachable(code),
                    not (needs_area and area is not None and area not in area_counts),
                    not self.catalog.has_equivalent_in(code, shareable),
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
            self._select(best, path, shared=shared)

    def _shareable_later(self, path: RequirementPath) -> Set[str]:
        """Courses listed later by programs that may share the current program's courses."""
        listed = self.listed_after_by_kind[path[0]]
        return set().union(*(codes for kind, codes in listed.items()
                             if rules.may_share(self.owner.kind, kind)))

    def _select_category(self, requirement: Requirement, path: RequirementPath) -> None:
        """
        Pick catalog courses matching a CATEGORY requirement until its minimums are met.

        Courses are preferred in this order: already credited (or shared, see
        ``_free``; a major's course a minor shares comes after the others, to
        save the minor's overlap), reachable prerequisites, then for a
        non-exclusive requirement courses a later requirement lists (so it can
        reuse them), then no enrollment restrictions, course code. Picks stay within
        ``max_independent_study_credits``. With ``single_department``, each
        department's best picks are compared and the winner is the first that
        meets the minimums with the fewest unreachable, then restricted, picks;
        then the most picks later requirements list (non-exclusive only); then
        the department with the most credited or already-selected courses (the
        student's prerequisites are likely there); then department name.
        """
        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        shared = not requirement.exclusive
        listed_later = self.listed_after[path[0]] if shared else set()
        available = {c: "A" for c in self.credited | set(self.selected) | self.mandatory}

        ranked = []
        for code in sorted(self.catalog):
            course = self.catalog[code]
            if (course.credits <= 0 or not course.offered
                    or not self.claims.can_claim(code, self.owner)
                    or (self._taken_or_planned(code) and not self._free(code))
                    or not category_matches(requirement, code, self.catalog)):
                continue
            unreachable = not course.prerequisites_satisfied(available)
            restricted = bool(course.restrictions)
            unlisted = not self.catalog.has_equivalent_in(code, listed_later)
            key = (not self._free(code), self.claims.is_overlap(code, self.owner),
                   unreachable, unlisted, restricted, code)
            ranked.append(((unreachable, restricted, unlisted), key, code))
        ranked.sort(key=lambda r: r[1])

        groups: Dict[str, List[Tuple[tuple, str]]] = {}
        for costs, _, code in ranked:
            department = self.catalog.department(code) if requirement.single_department else ""
            groups.setdefault(department, []).append((costs, code))

        def picks_from(candidates: List[Tuple[tuple, str]]) -> Tuple[bool, List[Tuple[tuple, str]]]:
            picked: List[Tuple[tuple, str]] = []
            seen: List[str] = []
            credits = 0
            for costs, code in candidates:
                if len(picked) >= min_courses and credits >= min_credits:
                    break
                if self.catalog.has_equivalent_in(code, set(seen)):
                    continue  # honors/base or cross-listed twin of a pick
                if not within_limits(requirement, seen, code, self.catalog):
                    continue
                picked.append((costs, code))
                seen.append(code)
                credits += self.catalog[code].credits
            return len(picked) >= min_courses and credits >= min_credits, picked

        planned = [self.catalog.department(c) for c in sorted(self.credited | set(self.selected))]
        best_key, best_picks = None, []
        for department, candidates in groups.items():
            met, picked = picks_from(candidates)
            totals = [sum(costs[i] for costs, _ in picked) for i in range(3)]
            score = (not met, *totals, -planned.count(department), department)
            if best_key is None or score < best_key:
                best_key, best_picks = score, picked
        for _, code in best_picks:
            self._select(code, path, shared=shared)

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


def _listed(requirement: Requirement) -> Iterator[str]:
    """Every course code a requirement lists, nested requirements included."""
    if requirement.course_code:
        yield requirement.course_code
    for item in (requirement.courses or []) + (requirement.choices or []):
        if isinstance(item, Requirement):
            yield from _listed(item)
        else:
            yield item
