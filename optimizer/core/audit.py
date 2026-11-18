"""
Degree audit: the one authority on whether requirements are satisfied.

``audit_requirements`` checks any list of course codes (a generated plan, a
hand-written one, or only what a student already has credit for) against a
list of requirements and reports, per requirement, whether it is met, which
courses were applied, the credits counted and, when unmet, why.

Semantics:

- Equivalent courses (honors/base pairs, cross-listed courses, see ``Catalog``)
  are the same course: a requirement listing ``CMSC131`` is met by
  ``CMSC131H``, and the plan counts each equivalence class once.
- ``COURSE`` needs its course. ``CHOICE`` needs any one of its choices (a code
  or a nested requirement).
- ``GROUP`` needs ``min_courses``, ``min_credits`` and ``min_areas`` (area =
  ``Catalog.primary_area``), with at most ``max_from_same_area`` applied courses
  per area. A GROUP with neither ``min_courses`` nor ``min_credits`` needs every
  listed course. Nested requirements are each audited; a GROUP with no
  quantity needs all of them, otherwise their courses count toward its totals.
- A course applied to one COURSE/CHOICE/GROUP requirement can't be applied to
  another.
- ``GEN_ED`` may reuse any course, including ones applied to major
  requirements. A course counts toward a category if one of its gen-ed options
  covers it (``rules.gen_ed_categories_satisfying``: DSNL also covers DSNS);
  counting it locks that option, so it can count toward that option's other
  categories but no longer toward its other options (see ``GenEdLedger``).
- ``CATEGORY`` needs ``min_courses``/``min_credits`` of plan courses passing its
  filters (``categories.category_matches``); with ``single_department`` they
  must all come from one department. Like GROUP courses, they can't be applied
  to another COURSE/CHOICE/GROUP/CATEGORY requirement.
- ``CREDIT_HOURS`` isn't supported and is reported unmet.

Assignment is a deterministic greedy pass, not a search. Requirements are
audited in the given order and each applies just enough courses, taken from
the plan in this preference order: courses from an area the GROUP still needs,
then courses fewer later requirements list (or, for a CATEGORY, match), then
the requirement's listed order. A CATEGORY prefers courses fewer later
requirements list or match, then course code, and with ``single_department``
uses the first department (by name) that meets it, else reports the one
closest to it. Gen-eds prefer courses whose option is already locked, then
courses with a single option, then course code. An unmet requirement releases the
courses it tried, so they stay available to later requirements. Limits: a
requirement never gives a course back once met, so an earlier requirement can
still take a course a later one needed when the tie-breaks above don't foresee
it (e.g. two later requirements competing for the same alternatives), area
choices aren't backtracked, and a gen-ed option locked by an earlier category
stays locked even if another option would have let more categories be met.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..models.catalog import Catalog
from ..models.course import Course
from ..models.requirements import Requirement, RequirementType
from .categories import category_matches
from .gen_eds import GenEdLedger


@dataclass(frozen=True)
class RequirementResult:
    """The audit of one requirement."""
    requirement: Requirement
    satisfied: bool
    applied: Tuple[str, ...] = ()  # courses counted toward it, nested ones included
    credits: int = 0               # credits of ``applied``
    reason: str = ""               # why it is unmet; empty when satisfied
    nested: Tuple['RequirementResult', ...] = ()


@dataclass(frozen=True)
class AuditReport:
    """Results for each audited requirement, in the order given."""
    results: Tuple[RequirementResult, ...]

    @property
    def satisfied(self) -> bool:
        return all(r.satisfied for r in self.results)

    @property
    def unmet(self) -> List[RequirementResult]:
        return [r for r in self.results if not r.satisfied]

    def __getitem__(self, requirement_id: str) -> RequirementResult:
        for result in self.results:
            if result.requirement.id == requirement_id:
                return result
        raise KeyError(requirement_id)


def audit_requirements(courses: Iterable[str], requirements: Sequence[Requirement],
                       catalog: Mapping[str, Course]) -> AuditReport:
    """
    Audit ``requirements`` (e.g. ``StudentDegreeProgram.get_all_requirements()``)
    against ``courses``: planned and already-credited course codes, in any order.
    """
    return _Auditor(courses, Catalog.of(catalog)).audit(requirements)


class _Auditor:
    def __init__(self, courses: Iterable[str], catalog: Catalog):
        self.catalog = catalog
        self.plan = catalog.dedupe_equivalents(sorted(set(courses)))
        self.plan_course: Dict[str, str] = {}  # any equivalent code -> the plan's course
        for code in self.plan:
            for equivalent in sorted(catalog.equivalents(code)):
                self.plan_course.setdefault(equivalent, code)
        self.used: Dict[str, str] = {}  # plan course -> id of the requirement it was applied to
        self.ledger = GenEdLedger(catalog)
        self.demand: Counter = Counter()  # plan course -> requirements not yet audited listing it

    def audit(self, requirements: Sequence[Requirement]) -> AuditReport:
        listed = [self._plan_codes(self._wanted(r)) for r in requirements]
        for codes in listed:
            self.demand.update(codes)
        results = []
        for requirement, codes in zip(requirements, listed):
            self.demand.subtract(codes)
            results.append(self._check(requirement))
        return AuditReport(tuple(results))

    def _wanted(self, requirement: Requirement) -> Iterator[str]:
        """
        Every course a requirement could use: the codes it lists, nested ones
        included, and for a CATEGORY the plan courses it matches.
        """
        if requirement.course_code:
            yield requirement.course_code
        if requirement.type == RequirementType.CATEGORY:
            yield from (c for c in self.plan if category_matches(requirement, c, self.catalog))
        for item in (requirement.courses or []) + (requirement.choices or []):
            if isinstance(item, Requirement):
                yield from self._wanted(item)
            else:
                yield item

    def _plan_codes(self, codes: Iterable[str]) -> List[str]:
        """The distinct plan courses matching ``codes``, in order."""
        return list(dict.fromkeys(self.plan_course[c] for c in codes if c in self.plan_course))

    def _check(self, requirement: Requirement) -> RequirementResult:
        """Audit ``requirement``; the courses it applied stay applied only if it is met."""
        used, ledger = dict(self.used), self.ledger.copy()
        handler = {
            RequirementType.COURSE: self._course,
            RequirementType.CHOICE: self._choice,
            RequirementType.GROUP: self._group,
            RequirementType.CATEGORY: self._category,
            RequirementType.GEN_ED: self._gen_ed,
        }.get(requirement.type)
        if handler is None:
            return RequirementResult(requirement, False,
                                     reason=f"{requirement.type.value} requirements are not supported")
        result = handler(requirement)
        if not result.satisfied:
            self.used, self.ledger = used, ledger
        return result

    def _available(self, code: str) -> Optional[str]:
        """The plan course for ``code`` (or an equivalent) if not applied elsewhere yet."""
        course = self.plan_course.get(code)
        return course if course is not None and course not in self.used else None

    def _missing(self, code: str) -> str:
        course = self.plan_course.get(code)
        return f"{code} (counted toward {self.used[course]})" if course in self.used else code

    def _credits(self, courses: Iterable[str]) -> int:
        return sum(self.catalog[c].credits for c in courses if c in self.catalog)

    def _result(self, requirement: Requirement, applied: List[str], problems: List[str],
                nested: Tuple[RequirementResult, ...] = ()) -> RequirementResult:
        for course in applied:
            self.used.setdefault(course, requirement.id)
        return RequirementResult(requirement, not problems, tuple(applied),
                                 self._credits(applied), "; ".join(problems), nested)

    def _course(self, requirement: Requirement) -> RequirementResult:
        course = self._available(requirement.course_code)
        if course:
            return self._result(requirement, [course], [])
        return self._result(requirement, [], [f"missing {self._missing(requirement.course_code)}"])

    def _choice(self, requirement: Requirement) -> RequirementResult:
        choices = requirement.choices or []
        codes = [c for c in choices if isinstance(c, str)]
        available = self._plan_codes(c for c in codes if self._available(c))
        if available:
            best = min(available, key=lambda c: (self.demand[c], available.index(c)))
            return self._result(requirement, [best], [])
        for item in choices:
            if isinstance(item, Requirement):
                nested = self._check(item)
                if nested.satisfied:
                    return self._result(requirement, list(nested.applied), [], (nested,))
        options = [self._missing(c) for c in codes] + [r.id for r in choices if isinstance(r, Requirement)]
        return self._result(requirement, [], [f"needs one of {', '.join(options)}"])

    def _group(self, requirement: Requirement) -> RequirementResult:
        items = requirement.courses or []
        nested = tuple(self._check(i) for i in items if isinstance(i, Requirement))
        applied = [c for r in nested if r.satisfied for c in r.applied]
        codes = list(dict.fromkeys(c for c in items if isinstance(c, str)))

        if requirement.min_courses is None and not requirement.min_credits:
            missing = []
            for code in codes:
                course = self._available(code)
                if course:
                    applied.append(course)
                else:
                    missing.append(self._missing(code))
            problems = [f"missing {', '.join(missing)}"] if missing else []
            problems += [f"{r.requirement.id} unmet ({r.reason})" for r in nested if not r.satisfied]
            return self._result(requirement, applied, problems, nested)

        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        min_areas = requirement.min_areas or 0
        cap = requirement.max_from_same_area
        area = self.catalog.primary_area
        areas = Counter(a for a in map(area, applied) if a)
        candidates = self._plan_codes(c for c in codes if self._available(c))

        def preference(course: str) -> tuple:
            new_area = len(areas) < min_areas and area(course) not in (None, *areas)
            return (not new_area, self.demand[course], candidates.index(course))

        while (len(applied) < min_courses or self._credits(applied) < min_credits
               or len(areas) < min_areas):
            eligible = [c for c in candidates if c not in applied
                        and not (cap is not None and area(c) and areas[area(c)] >= cap)]
            if not eligible:
                break
            best = min(eligible, key=preference)
            applied.append(best)
            if area(best):
                areas[area(best)] += 1

        credits = self._credits(applied)
        problems = [] if items else ["lists no courses"]
        if len(applied) < min_courses:
            problems.append(f"needs {min_courses} courses, has {len(applied)}")
        if credits < min_credits:
            problems.append(f"needs {min_credits} credits, has {credits}")
        if len(areas) < min_areas:
            problems.append(f"needs courses from {min_areas} areas, has {len(areas)}")
        over = sorted(a for a, n in areas.items() if cap is not None and n > cap)
        if over:
            problems.append(f"more than {cap} courses from {', '.join(over)}")
        return self._result(requirement, applied, problems, nested)

    def _category(self, requirement: Requirement) -> RequirementResult:
        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        candidates = sorted(
            (c for c in self.plan
             if c not in self.used and category_matches(requirement, c, self.catalog)),
            key=lambda c: (self.demand[c], c),
        )
        groups: Dict[str, List[str]] = {}
        for course in candidates:
            department = self.catalog.department(course) if requirement.single_department else ""
            groups.setdefault(department, []).append(course)

        best: Optional[Tuple[tuple, List[str]]] = None
        for department in sorted(groups):
            applied: List[str] = []
            for course in groups[department]:
                if len(applied) >= min_courses and self._credits(applied) >= min_credits:
                    break
                applied.append(course)
            met = len(applied) >= min_courses and self._credits(applied) >= min_credits
            closeness = (0, 0, 0) if met else (1, -self._credits(applied), -len(applied))
            if best is None or closeness < best[0]:
                best = (closeness, applied)
        applied = best[1] if best else []

        credits = self._credits(applied)
        where = " from one department" if requirement.single_department else ""
        problems = []
        if len(applied) < min_courses:
            problems.append(f"needs {min_courses} matching courses{where}, has {len(applied)}")
        if credits < min_credits:
            problems.append(f"needs {min_credits} matching credits{where}, has {credits}")
        return self._result(requirement, applied, problems)

    def _gen_ed(self, requirement: Requirement) -> RequirementResult:
        category = requirement.gen_ed_category
        min_courses = requirement.min_courses or 1
        min_credits = requirement.min_credits or 0

        def preference(course: str) -> int:
            if course in self.ledger.locked:
                return 0
            return 1 if len(self.catalog[course].gen_ed_options) <= 1 else 2

        candidates = sorted((c for c in self.plan if self.ledger.option_for(c, category)),
                            key=preference)
        applied: List[str] = []
        for course in candidates:
            if len(applied) >= min_courses and self._credits(applied) >= min_credits:
                break
            self.ledger.count(course, category)
            applied.append(course)

        credits = self._credits(applied)
        problems = []
        if len(applied) < min_courses:
            problems.append(f"needs {min_courses} {category} courses, has {len(applied)}")
        if credits < min_credits:
            problems.append(f"needs {min_credits} {category} credits, has {credits}")
        return RequirementResult(requirement, not problems, tuple(applied), credits, "; ".join(problems))
