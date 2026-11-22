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
  another, except across programs as ``ClaimLedger`` allows when ``owners``
  are given: majors may share with each other, a minor may share up to
  ``rules.within_major_minor_overlap`` of its majors' courses, and unshared
  courses are used first.
- ``DISTRIBUTION`` checks the courses earlier requirements of the same
  program applied (see ``owners``): those with an area that pass its CATEGORY
  filters must span
  ``min_areas`` areas, at most ``max_from_same_area`` each. It applies none.
- GROUP ``min_areas_ignore`` areas don't count toward ``min_areas``; at most
  one course of each ``mutually_exclusive`` set is applied.
- ``GEN_ED`` may reuse any course, including ones applied to major
  requirements. A course counts toward a category if one of its gen-ed options
  covers it (``rules.gen_ed_categories_satisfying``: DSNL also covers DSNS);
  counting it locks that option, so it can count toward that option's other
  categories but no longer toward its other options (see ``GenEdLedger``).
- ``CATEGORY`` needs ``min_courses``/``min_credits`` of plan courses passing its
  filters (``categories.category_matches``); with ``single_department`` they
  must all come from one department, and with ``max_independent_study_credits``
  at most that many credits may come from independent study or experiential
  learning (``rules.is_independent_study``). Like GROUP courses, they can't be
  applied to another COURSE/CHOICE/GROUP/CATEGORY requirement.
- A requirement with ``exclusive`` false (e.g. the CS Upper Level
  Concentration, which may overlap with a minor) still can't use courses an
  earlier requirement applied, but leaves its own courses available to later
  ones.
- ``CREDIT_HOURS`` needs ``min_credits`` from every plan course passing its
  filters (the same ones as CATEGORY; none means every course). It doesn't
  apply courses exclusively: they still count toward other requirements.
  ``prior_credits`` (credits earned outside the listed courses) count only
  toward a CREDIT_HOURS with no filters, since their courses are unknown.

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
from dataclasses import dataclass, replace
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..models.catalog import Catalog
from ..models.course import Course
from ..models.requirements import Requirement, RequirementType
from ..models.schedule import Semester
from ..models.student import DEGREE, CourseRequest, RequirementOwner
from .claims import ClaimLedger
from .categories import category_matches, credit_hours, within_limits
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
                       catalog: Mapping[str, Course], prior_credits: int = 0,
                       owners: Optional[Sequence[RequirementOwner]] = None) -> AuditReport:
    """
    Audit ``requirements`` (e.g. ``StudentDegreeProgram.get_all_requirements()``)
    against ``courses``: planned and already-credited course codes, in any order.
    ``prior_credits`` are credits already earned from courses not in ``courses``
    or not in the catalog. ``owners`` gives the program each requirement
    belongs to (``StudentDegreeProgram.owned_requirements``), so a minor can
    share courses with a major; without it, nothing is shared.
    """
    owners = list(owners) if owners is not None else [DEGREE] * len(requirements)
    if len(owners) != len(requirements):
        raise ValueError("owners must give one owner per requirement")
    return _Auditor(courses, Catalog.of(catalog), prior_credits).audit(requirements, owners)


def audit_benchmarks(benchmarks: Sequence[Tuple[int, Requirement]],
                     semesters: Sequence[Semester], catalog: Mapping[str, Course],
                     credited: Iterable[str] = (), credits_completed: int = 0
                     ) -> List[RequirementResult]:
    """
    Audit limited-enrollment benchmarks (``(credits, requirement)`` pairs, see
    ``MajorRequirements.benchmark_requirements``). Each must be met by the
    courses finished by the end of the semester in which cumulative credits
    (``credits_completed`` plus the credits of each planned semester) first
    reach ``credits``: the ``credited`` courses and that semester's and earlier
    ones. A plan that never reaches it counts every planned course. Each
    benchmark is audited on its own, so its courses may also count toward
    degree requirements and other benchmarks. Grades aren't checked.
    """
    catalog = Catalog.of(catalog)
    results = []
    for credits, requirement in benchmarks:
        courses, due = _courses_by(semesters, catalog, credited, credits_completed, credits=credits)
        result = audit_requirements(courses, [requirement], catalog)[requirement.id]
        if not result.satisfied:
            result = replace(result, reason=f"{due} ({credits} credits): {result.reason}")
        results.append(result)
    return results


def audit_requests(requests: Sequence[CourseRequest], semesters: Sequence[Semester],
                   catalog: Mapping[str, Course], credited: Iterable[str] = (),
                   credits_completed: int = 0) -> List[RequirementResult]:
    """
    Audit the student's requested courses (``StudentProfile.requested_courses``):
    each, as a COURSE requirement ``requested_{code}``, must be credited or
    planned by its deadline: the end of the plan's ``by_semester``th semester
    (counting Fall and Spring terms from the first planned semester; a Summer or
    Winter term counts with the semester after it) and of the
    semester in which cumulative credits reach ``by_credits`` (as for
    ``audit_benchmarks``); with neither, by the end of the plan.
    """
    catalog = Catalog.of(catalog)
    results = []
    for request in requests:
        requirement = Requirement(id=f"requested_{request.code}",
                                  name=f"Requested: {request.code} {request.deadline}",
                                  type=RequirementType.COURSE, course_code=request.code)
        courses, due = _courses_by(semesters, catalog, credited, credits_completed,
                                   credits=request.by_credits, semester=request.by_semester)
        result = audit_requirements(courses, [requirement], catalog)[requirement.id]
        if not result.satisfied:
            reason = (f"{request.code} isn't in the catalog" if request.code not in catalog
                      else f"{request.deadline} ({due}): {result.reason}")
            result = replace(result, reason=reason)
        results.append(result)
    return results


def _term_number(semester: Semester) -> int:
    """
    Consecutive numbers for Fall/Spring semesters (Fall 2025 -> Spring 2026 ->
    Fall 2026). A Summer or Winter term gets the number of the semester after
    it, so it counts toward deadlines from that semester on.
    """
    return semester.year * 2 + (semester.type.value in ("Fall", "Summer"))


def _courses_by(semesters: Sequence[Semester], catalog: Catalog, credited: Iterable[str],
                credits_completed: int, credits: Optional[int] = None,
                semester: Optional[int] = None) -> Tuple[List[str], str]:
    """
    The credited courses plus those planned through the deadline's semester,
    and a label for it: the semester in which cumulative credits first reach
    ``credits`` and the ``semester``th of the plan, whichever is earlier (the
    whole plan if neither is given or reached).
    """
    courses, total, due = list(credited), credits_completed, "before the plan"
    first = _term_number(semesters[0]) if semesters else 0
    for planned in semesters:
        if ((credits is not None and total >= credits)
                or (semester is not None and _term_number(planned) - first >= semester)):
            break
        courses.extend(planned.courses)
        total += planned.total_credits(catalog)
        due = f"by {planned}"
    else:
        if (credits is not None and total < credits) or credits is None and semester is None:
            due = "by the end of the plan"
    return courses, due


class _Auditor:
    def __init__(self, courses: Iterable[str], catalog: Catalog, prior_credits: int = 0):
        self.catalog = catalog
        self.prior_credits = prior_credits
        self.plan = catalog.dedupe_equivalents(sorted(set(courses)))
        self.plan_course: Dict[str, str] = {}  # any equivalent code -> the plan's course
        for code in self.plan:
            for equivalent in sorted(catalog.equivalents(code)):
                self.plan_course.setdefault(equivalent, code)
        self.used: Dict[str, str] = {}  # plan course -> id of the requirement it was applied to
        self.claims = ClaimLedger(catalog)
        self.owner = DEGREE  # the program of the requirement being audited
        self.ledger = GenEdLedger(catalog)
        self.demand: Counter = Counter()  # plan course -> requirements not yet audited listing it

    def audit(self, requirements: Sequence[Requirement],
              owners: Sequence[RequirementOwner]) -> AuditReport:
        listed = [self._plan_codes(self._wanted(r)) for r in requirements]
        for codes in listed:
            self.demand.update(codes)
        results = []
        for requirement, owner, codes in zip(requirements, owners, listed):
            self.demand.subtract(codes)
            self.owner = owner
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
        used, ledger, claims = dict(self.used), self.ledger.copy(), self.claims.copy()
        handler = {
            RequirementType.COURSE: self._course,
            RequirementType.CHOICE: self._choice,
            RequirementType.GROUP: self._group,
            RequirementType.CATEGORY: self._category,
            RequirementType.CREDIT_HOURS: self._credit_hours,
            RequirementType.DISTRIBUTION: self._distribution,
            RequirementType.GEN_ED: self._gen_ed,
        }.get(requirement.type)
        if handler is None:
            return RequirementResult(requirement, False,
                                     reason=f"{requirement.type.value} requirements are not supported")
        result = handler(requirement)
        if not result.satisfied:
            self.used, self.ledger, self.claims = used, ledger, claims
        elif not requirement.exclusive:
            self.used, self.claims = used, claims  # its courses stay available to later requirements
        return result

    def _available(self, code: str) -> Optional[str]:
        """
        The plan course for ``code`` (or an equivalent) if not applied
        elsewhere yet, or applied to a major that the current minor may share it with.
        """
        course = self.plan_course.get(code)
        return course if course is not None and self.claims.can_claim(course, self.owner) else None

    def _overlap(self, course: str) -> bool:
        """Whether applying ``course`` uses up some of the minor's major overlap."""
        return self.claims.is_overlap(course, self.owner)

    def _missing(self, code: str) -> str:
        course = self.plan_course.get(code)
        if course not in self.used:
            return code
        if self.claims.is_overlap(course, self.owner):
            shared = ", ".join(self.claims.shared(self.owner)) or "none"
            return (f"{code} (counted toward {self.used[course]}; over the overlap limit or "
                    f"already shared; {self.owner.code} shares: {shared})")
        return f"{code} (counted toward {self.used[course]})"

    def _credits(self, courses: Iterable[str]) -> int:
        return sum(self.catalog[c].credits for c in courses if c in self.catalog)

    def _result(self, requirement: Requirement, applied: List[str], problems: List[str],
                nested: Tuple[RequirementResult, ...] = ()) -> RequirementResult:
        for course in applied:
            self.used.setdefault(course, requirement.id)
            self.claims.claim(course, self.owner)
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
            best = min(available, key=lambda c: (self._overlap(c), self.demand[c], available.index(c)))
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
                    self.claims.claim(course, self.owner)  # so the overlap cap sees it
                else:
                    missing.append(self._missing(code))
            problems = [f"missing {', '.join(missing)}"] if missing else []
            problems += [f"{r.requirement.id} unmet ({r.reason})" for r in nested if not r.satisfied]
            return self._result(requirement, applied, problems, nested)

        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        min_areas = requirement.min_areas or 0
        ignored = set(requirement.min_areas_ignore or ())
        exclusive_sets = [set(self._plan_codes(s)) for s in requirement.mutually_exclusive or ()]
        cap = requirement.max_from_same_area
        area = self.catalog.primary_area
        areas = Counter(a for a in map(area, applied) if a)
        candidates = self._plan_codes(c for c in codes if self._available(c))

        def counted() -> set:
            return set(areas) - ignored

        def excluded(course: str) -> bool:
            return any(course in s and not s.isdisjoint(applied) for s in exclusive_sets)

        def preference(course: str) -> tuple:
            new_area = (len(counted()) < min_areas
                        and area(course) not in (None, *areas, *ignored))
            return (self._overlap(course), not new_area, self.demand[course],
                    candidates.index(course))

        while (len(applied) < min_courses or self._credits(applied) < min_credits
               or len(counted()) < min_areas):
            eligible = [c for c in candidates if c not in applied
                        and self.claims.can_claim(c, self.owner) and not excluded(c)
                        and not (cap is not None and area(c) and areas[area(c)] >= cap)]
            if not eligible:
                break
            best = min(eligible, key=preference)
            applied.append(best)
            self.claims.claim(best, self.owner)
            if area(best):
                areas[area(best)] += 1

        credits = self._credits(applied)
        problems = [] if items else ["lists no courses"]
        if len(applied) < min_courses:
            problems.append(f"needs {min_courses} courses, has {len(applied)}")
        if credits < min_credits:
            problems.append(f"needs {min_credits} credits, has {credits}")
        if len(counted()) < min_areas:
            not_counting = f" (not counting {', '.join(sorted(ignored))})" if ignored else ""
            problems.append(f"needs courses from {min_areas} areas{not_counting}, has {len(counted())}")
        over = sorted(a for a, n in areas.items() if cap is not None and n > cap)
        if over:
            problems.append(f"more than {cap} courses from {', '.join(over)}")
        return self._result(requirement, applied, problems, nested)

    def _category(self, requirement: Requirement) -> RequirementResult:
        min_courses = requirement.min_courses or 0
        min_credits = requirement.min_credits or 0
        candidates = sorted(
            (c for c in self.plan
             if self.claims.can_claim(c, self.owner)
             and category_matches(requirement, c, self.catalog)),
            key=lambda c: (self._overlap(c), self.demand[c], c),
        )
        groups: Dict[str, List[str]] = {}
        for course in candidates:
            department = self.catalog.department(course) if requirement.single_department else ""
            groups.setdefault(department, []).append(course)

        best: Optional[Tuple[tuple, List[str], bool]] = None
        for department in sorted(groups):
            applied: List[str] = []
            capped = False  # an independent study course was left out by the cap
            claims = self.claims.copy()  # this department's trial picks
            for course in groups[department]:
                if len(applied) >= min_courses and self._credits(applied) >= min_credits:
                    break
                if not claims.can_claim(course, self.owner):
                    continue  # the minor's overlap with the major is full
                if within_limits(requirement, applied, course, self.catalog):
                    applied.append(course)
                    claims.claim(course, self.owner)
                else:
                    capped = True
            met = len(applied) >= min_courses and self._credits(applied) >= min_credits
            closeness = (0, 0, 0) if met else (1, -self._credits(applied), -len(applied))
            if best is None or closeness < best[0]:
                best = (closeness, applied, capped)
        applied, capped = (best[1], best[2]) if best else ([], False)

        credits = self._credits(applied)
        where = " from one department" if requirement.single_department else ""
        problems = []
        if len(applied) < min_courses:
            problems.append(f"needs {min_courses} matching courses{where}, has {len(applied)}")
        if credits < min_credits:
            problems.append(f"needs {min_credits} matching credits{where}, has {credits}")
        if problems and capped:
            problems.append(f"at most {requirement.max_independent_study_credits} "
                            "independent study credits count")
        return self._result(requirement, applied, problems)

    def _credit_hours(self, requirement: Requirement) -> RequirementResult:
        applied, credits = credit_hours(requirement, self.plan, self.catalog, self.prior_credits)
        problems = []
        if credits < (requirement.min_credits or 0):
            problems.append(f"needs {requirement.min_credits} credits, has {credits}")
        if len(applied) < (requirement.min_courses or 0):
            problems.append(f"needs {requirement.min_courses} courses, has {len(applied)}")
        return RequirementResult(requirement, not problems, tuple(applied), credits, "; ".join(problems))

    def _distribution(self, requirement: Requirement) -> RequirementResult:
        courses = [c for c in self.claims.courses_of(self.owner)
                   if self.catalog.primary_area(c) and category_matches(requirement, c, self.catalog)]
        areas = Counter(map(self.catalog.primary_area, courses))
        problems = []
        if len(areas) < requirement.min_areas:
            problems.append(f"needs courses from {requirement.min_areas} areas, has {len(areas)}"
                            + (f" ({', '.join(sorted(areas))})" if areas else ""))
        cap = requirement.max_from_same_area
        over = sorted(a for a, n in areas.items() if cap is not None and n > cap)
        if over:
            problems.append(f"more than {cap} courses from {', '.join(over)}")
        return RequirementResult(requirement, not problems, tuple(courses), self._credits(courses),
                                 "; ".join(problems))

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
