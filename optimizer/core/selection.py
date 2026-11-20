"""Choose the courses that satisfy a degree program's requirements."""

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from ..models.catalog import Catalog
from ..models.course import Course, PrerequisiteCondition, PrerequisiteType
from ..models.requirements import Requirement, RequirementType
from ..models.student import DEGREE, RequirementOwner, StudentDegreeProgram
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

    prerequisites: Tuple[str, ...] = ()
    """
    Courses added only because a selected course needs them and no
    requirement asked for them (e.g. MATH246 for ENME480), in the order added.
    """
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
        self.prerequisites: Dict[str, None] = {}
        # Codes listed by requirements after each top-level index, in total and
        # per program.
        self.listed_after: List[Set[str]] = []
        self.listed_after_by_owner: List[Dict[RequirementOwner, Set[str]]] = []
        later: Set[str] = set()
        later_by_owner: Dict[RequirementOwner, Set[str]] = {}
        for owner, req in reversed(self.owned):
            self.listed_after.append(set(later))
            self.listed_after_by_owner.append({o: set(c) for o, c in later_by_owner.items()})
            later.update(_listed(req))
            later_by_owner.setdefault(owner, set()).update(_listed(req))
        self.listed_after.reverse()
        self.listed_after_by_owner.reverse()
        # The first DISTRIBUTION requirement of the same program after each top-level index.
        self.distribution_after: List[Optional[Requirement]] = []
        upcoming: Dict[RequirementOwner, Requirement] = {}
        for owner, req in reversed(self.owned):
            self.distribution_after.append(upcoming.get(owner))
            if req.type == RequirementType.DISTRIBUTION:
                upcoming[owner] = req
        self.distribution_after.reverse()

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
        self._add_missing_prerequisites()
        for requirement, path in sorted(self.credit_minimums, key=lambda rp: not has_filters(rp[0])):
            self._select_electives(requirement, path)
        return Selection(
            courses=tuple(self.catalog.dedupe_equivalents(self.selected)),
            by_requirement=MappingProxyType({p: tuple(c) for p, c in self.assigned.items()}),
            gen_ed_options=MappingProxyType(self.gen_eds.locked),
            electives=tuple(self.electives),
            prerequisites=tuple(self.prerequisites),
        )

    def _add_missing_prerequisites(self) -> None:
        """
        Add the courses selected courses need that neither requirements nor
        credit cover, so every selected course can be scheduled: for an OR the
        alternative already met, else the first one whose own prerequisites
        can be met too; then the added courses' own prerequisites. Courses missing from the catalog
        can't be added; a course needing one stays unschedulable.
        """
        queue = list(self.selected)
        for code in queue:  # grows as prerequisites are added
            course = self.catalog.get(code)
            for condition in course.prerequisites if course else ():
                for needed in self._courses_for(condition, {code}) or ():
                    if not self._taken_or_planned(needed):
                        self.selected[needed] = None
                        self.prerequisites[needed] = None
                        queue.append(needed)

    def _courses_for(self, condition: PrerequisiteCondition, visiting: Set[str]) -> Optional[List[str]]:
        """Courses to add so ``condition`` holds ([] if it already does), or None if it can't."""
        def addable(code: str) -> bool:
            """In the catalog, not already being added, and its own prerequisites can be met."""
            if code not in self.catalog or code in visiting or self._taken_or_planned(code):
                return False  # missing, already being added, or no credit (overlaps a planned course)
            inner = visiting | {code}
            return all(self._courses_for(c, inner) is not None
                       for c in self.catalog[code].prerequisites)

        if condition.type == PrerequisiteType.COURSE:
            missing = [c for c in condition.courses or [] if not self._planned(c)]
            return missing if all(addable(c) for c in missing) else None
        if condition.type == PrerequisiteType.AND:
            needed: List[str] = []
            for nested in condition.conditions or []:
                part = self._courses_for(nested, visiting)
                if part is None:
                    return None
                needed += [c for c in part if c not in needed]
            return needed
        # OR: an alternative already met, else the first that can be met
        options = [[c] if not self._planned(c) else [] for c in condition.courses or []
                   if self._planned(c) or addable(c)]
        options += [o for o in (self._courses_for(c, visiting) for c in condition.conditions or [])
                    if o is not None]
        if any(option == [] for option in options):
            return []
        return options[0] if options else None

    def _collect_mandatory(self, requirement: Requirement) -> None:
        """
        Gather courses that will certainly be taken (single-course requirements
        and groups needing every listed course), so prerequisite checks can
        count on them.
        """
        if requirement.type == RequirementType.COURSE and requirement.course_code:
            self.mandatory.add(requirement.course_code)
        if (requirement.type == RequirementType.GROUP and requirement.min_courses is None
                and not requirement.min_credits):
            self.mandatory.update(c for c in requirement.courses or [] if isinstance(c, str))
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

    def _planned(self, code: str) -> bool:
        """Whether ``code`` or an equivalent is credited or planned (so it meets a prerequisite)."""
        return self.catalog.has_equivalent_in(code, self.credited | set(self.selected))

    def _taken_or_planned(self, code: str) -> bool:
        """Whether ``code``, an equivalent, or a course sharing its credit is credited or planned."""
        done = self.credited | set(self.selected)
        return self.catalog.has_equivalent_in(code, done) or self.catalog.has_credit_conflict_in(code, done)

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
                    # the option needing the fewest new courses, all of them in the catalog
                    index, best = min(nested, key=lambda ic: (self._option_cost(ic[1]), ic[0]))
                    self._select_for_requirement(best, path + (index,))

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
                    ignored_areas=requirement.min_areas_ignore or (),
                    exclusive_sets=requirement.mutually_exclusive or (),
                )

        elif rtype == RequirementType.CATEGORY:
            self._select_category(requirement, path)

        elif rtype == RequirementType.DISTRIBUTION:
            pass  # a check on the program's courses; _pick_from_group steers toward it

        elif rtype == RequirementType.CREDIT_HOURS:
            self.credit_minimums.append((requirement, path))  # filled at the end of run()

        elif rtype == RequirementType.GEN_ED:
            if requirement.gen_ed_category:
                self._select_gen_ed(requirement, path)

    def _option_cost(self, requirement: Requirement) -> Tuple[int, int]:
        """
        Roughly what satisfying ``requirement`` would take: (courses it needs
        that aren't in the catalog, new courses it adds). Courses credited,
        already planned or shareable cost nothing.
        """
        def course_cost(code: str) -> Tuple[int, int]:
            if code not in self.catalog:
                return (1, 0)
            if self._free(code) or self._taken_or_planned(code):
                return (0, 0)
            return (0, 1)

        items = [course_cost(i) if isinstance(i, str) else self._option_cost(i)
                 for i in (requirement.courses or []) + (requirement.choices or [])]
        if requirement.type == RequirementType.COURSE:
            return course_cost(requirement.course_code)
        if requirement.type == RequirementType.CHOICE:
            return min(items, default=(1, 0))
        if requirement.type == RequirementType.GROUP:
            if requirement.min_courses is None and not requirement.min_credits:
                needed = items
            else:
                needed = sorted(items)[:max(requirement.min_courses or 0, 1)]
            return (sum(m for m, _ in needed), sum(n for _, n in needed))
        return (0, requirement.min_courses or 1)

    def _pick_from_group(self, codes: List[str], path: RequirementPath, min_courses: int = 0,
                         min_credits: int = 0, min_areas: int = 0,
                         max_per_area: Optional[int] = None, shared: bool = False,
                         ignored_areas: Sequence[str] = (),
                         exclusive_sets: Sequence[Sequence[str]] = ()) -> None:
        """
        Pick courses from ``codes`` until the count/credit/area minimums are met.

        Areas in ``ignored_areas`` don't count toward ``min_areas``; at most one
        course of each of ``exclusive_sets`` is picked.

        Preference order: courses already credited (or picked by a
        non-exclusive requirement, which this one may reuse), then a major's
        course this minor may share, then courses whose prerequisites are reachable,
        then courses from a not-yet-covered area (while ``min_areas``, or a
        later DISTRIBUTION requirement of the program, is unmet), then courses
        another later program that may share this one's courses lists
        (``rules.may_share``), then the order the requirement lists them.
        """
        shareable = self._shareable_later(path)
        distribution = self.distribution_after[path[0]]
        program_areas = self._program_areas(distribution)
        candidates = list(dict.fromkeys(
            c for c in codes if c in self.catalog and self.claims.can_claim(c, self.owner)
        ))
        picked: List[str] = []
        credits = 0
        area_counts: Counter = Counter()  # every picked course's area, for max_per_area
        counted_areas: Set[str] = set()   # the areas that count toward min_areas

        def satisfied() -> bool:
            return (len(picked) >= min_courses and credits >= min_credits
                    and len(counted_areas) >= min_areas)

        def program_needs_area() -> bool:
            return (distribution is not None
                    and len(set(program_areas) | set(area_counts)) < (distribution.min_areas or 0))

        def excluded(code: str) -> bool:
            return any(code in group and any(p in group for p in picked) for group in exclusive_sets)

        while not satisfied():
            best, best_key = None, None
            for index, code in enumerate(candidates):
                if code in picked or (self._taken_or_planned(code) and not self._free(code)):
                    continue  # already planned via another requirement or an equivalent
                if excluded(code):
                    continue
                area = self.catalog.primary_area(code)
                if max_per_area is not None and area and area_counts[area] >= max_per_area:
                    continue
                new_area = area is not None and (
                    (len(counted_areas) < min_areas and area not in ignored_areas
                     and area not in counted_areas)
                    or (program_needs_area() and area not in program_areas
                        and area not in area_counts
                        and category_matches(distribution, code, self.catalog)))
                key = (
                    not self._free(code),
                    self.claims.is_overlap(code, self.owner),
                    not self._reachable(code),
                    not new_area,
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
                if area not in ignored_areas:
                    counted_areas.add(area)
            self._select(best, path, shared=shared)

    def _program_areas(self, distribution: Optional[Requirement]) -> Counter:
        """
        Areas (``Catalog.primary_area``) of the courses the current program
        counts so far that pass ``distribution``'s filters.
        """
        if distribution is None:
            return Counter()
        return Counter(self.catalog.primary_area(c) for c in self.claims.courses_of(self.owner)
                       if self.catalog.primary_area(c)
                       and category_matches(distribution, c, self.catalog))

    def _shareable_later(self, path: RequirementPath, unlimited_only: bool = False) -> Set[str]:
        """
        Courses listed later by other programs that may share the current
        program's courses (with ``unlimited_only``, only programs whose overlap
        isn't capped: majors, not minors).
        """
        listed = self.listed_after_by_owner[path[0]]
        return set().union(*(
            codes for owner, codes in listed.items()
            if owner != self.owner and rules.may_share(self.owner.kind, owner.kind)
            and not (unlimited_only and rules.overlap_is_limited(owner.kind))))

    def _select_category(self, requirement: Requirement, path: RequirementPath) -> None:
        """
        Pick catalog courses matching a CATEGORY requirement until its minimums are met.

        Courses are preferred in this order: already credited (or shared, see
        ``_free``; a major's course a minor shares comes after the others, to
        save the minor's overlap), reachable prerequisites, then courses a
        later requirement lists (so it can reuse them; for an exclusive
        requirement only later programs with unlimited overlap, i.e. majors),
        then no enrollment restrictions, not independent study, codes passing
        the filters themselves rather than through a cross-listing, course code. Picks stay within
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
        # A non-exclusive requirement leaves its picks to any later requirement;
        # an exclusive one can still share with later programs whose overlap is unlimited
        listed_later = (self.listed_after[path[0]] if shared
                        else self._shareable_later(path, unlimited_only=True))
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
            cross_listed_match = not category_matches(requirement, code, self.catalog, equivalents=False)
            key = (not self._free(code), self.claims.is_overlap(code, self.owner),
                   unreachable, unlisted, restricted, rules.is_independent_study(course),
                   cross_listed_match, code)
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
        Add free electives until a CREDIT_HOURS requirement's ``min_credits``
        and ``min_courses`` are met.

        Candidates are offered undergraduate courses passing the requirement's
        filters that aren't planned or credited yet, numbered 100-499
        (``rules.earns_degree_credit``). They're preferred in this order: no
        enrollment restrictions, reachable prerequisites, not independent
        study (``rules.is_independent_study``), not limited
        per semester (``rules.counts_toward_upper_level_cmsc_cap``, so electives
        don't crowd required courses out of a semester), offered in the most
        terms (they're scheduled last, into whatever room is left), credits closest to
        ``rules.TYPICAL_COURSE_CREDITS``, departments with the most
        planned or credited courses (likely to suit the student), then course code.
        """
        def short() -> bool:
            plan = self.catalog.dedupe_equivalents(sorted(self.credited) + list(self.selected))
            counted, credits = credit_hours(requirement, plan, self.catalog, self.prior_credits)
            return (credits < (requirement.min_credits or 0)
                    or len(counted) < (requirement.min_courses or 0))

        if not short():
            return

        planned = [self.catalog.department(c) for c in sorted(self.credited | set(self.selected))]
        available = {c: "A" for c in self.credited | set(self.selected) | self.mandatory}
        candidates = []
        for code in sorted(self.catalog):
            course = self.catalog[code]
            if (course.credits <= 0 or not course.offered or not rules.earns_degree_credit(course)
                    or self._taken_or_planned(code)
                    or not category_matches(requirement, code, self.catalog)):
                continue
            key = (bool(course.restrictions), not course.prerequisites_satisfied(available),
                   rules.is_independent_study(course),
                   rules.counts_toward_upper_level_cmsc_cap(course),
                   -len(course.offered),
                   abs(course.credits - rules.TYPICAL_COURSE_CREDITS),
                   -planned.count(self.catalog.department(code)), code)
            candidates.append((key, code))
        candidates.sort()

        for _, code in candidates:
            if not short():
                break
            if self._taken_or_planned(code):
                continue  # an equivalent was picked earlier in this loop
            self._select(code, path, claim=False)
            self.electives[code] = None

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
