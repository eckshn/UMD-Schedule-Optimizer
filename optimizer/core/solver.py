"""
Place courses into terms with a constraint solver (OR-Tools CP-SAT).

``solve_schedule`` builds one model of the whole plan. Hard constraints:

- each course goes in at most one term the course is offered in;
- prerequisites come from earlier terms and corequisites from earlier terms
  or the same one (each condition tree as ``PrerequisiteCondition`` reads it;
  credited courses and their equivalents count as met when their grade meets
  the condition's minimum, else a planned retake must come first);
- each term stays within its credit maximum (``rules.credit_load``), Summer
  and Winter within their course limit (``rules.course_limit``), every term
  within the upper-level CMSC cap, and courses needing prior credits
  (``rules.credits_required_before``, FSPW) come after enough of them.

The objective, from the heaviest weight down: place every course; meet
benchmark and request deadlines; finish in as few terms as possible; keep
Fall/Spring semesters at least at the preferred minimum and close to each
other; keep each term within the difficulty maximum; take required (non
elective) courses early.

The solver runs on one worker with a fixed seed and a deterministic time
limit, so the same input always gives the same schedule. It starts from a
hint (the greedy schedule) and returns None if it finds nothing better
than infeasible, so callers can fall back.
"""

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..models.catalog import Catalog
from ..models.course import PrerequisiteCondition, PrerequisiteType
from ..models.grades import meets_minimum
from ..models.schedule import Schedule, Semester, SemesterType
from ..models.student import StudentProfile
from . import rules

try:
    from ortools.sat.python import cp_model
except ImportError:  # optional: the greedy scheduler is used without it
    cp_model = None

# Objective weights (see the module docstring)
UNPLACED = 100_000
MISSED_DEADLINE = 10_000
TERM_USED = 1_000
SHORTFALL = 30      # per credit below the preferred minimum in a used Fall/Spring semester
SPREAD = 40         # per credit between the heaviest and lightest used Fall/Spring semester
DIFFICULTY = 2      # per 0.1 difficulty over the maximum
EARLY = 1           # per term a required course waits

# Solver effort, in CP-SAT's deterministic time units (roughly seconds)
DETERMINISTIC_TIME_LIMIT = 10.0


def available() -> bool:
    """Whether OR-Tools is installed."""
    return cp_model is not None


def solve_schedule(courses: Sequence[str], catalog: Catalog, student: StudentProfile,
                   terms: Sequence[Tuple[int, SemesterType]],
                   electives: Iterable[str] = (),
                   credit_deadlines: Optional[Mapping[str, int]] = None,
                   semester_deadlines: Optional[Mapping[str, int]] = None,
                   hint: Optional[Schedule] = None) -> Optional[Schedule]:
    """
    Schedule ``courses`` (plan course codes, credited ones already removed)
    over ``terms`` (chronological ``(year, type)`` pairs). ``credit_deadlines``
    maps a course to the cumulative credits it must be taken by (the end of
    the term in which they're reached, as for benchmarks); ``semester_deadlines``
    to the number of Fall/Spring semesters it must be taken within (a Summer
    or Winter term counts with the semester after it). Returns None when
    OR-Tools is missing or no solution is found.
    """
    if cp_model is None:
        return None
    model = _Model(courses, catalog, student, terms, set(electives),
                   credit_deadlines or {}, semester_deadlines or {})
    if hint is not None:
        model.add_hint(hint)
    return model.solve()


class _Model:
    def __init__(self, courses: Sequence[str], catalog: Catalog, student: StudentProfile,
                 terms: Sequence[Tuple[int, SemesterType]], electives: Set[str],
                 credit_deadlines: Mapping[str, int], semester_deadlines: Mapping[str, int]):
        self.catalog = catalog
        self.student = student
        self.terms = list(terms)
        self.courses = [c for c in dict.fromkeys(courses) if c in catalog]
        self.grades = student.grades()
        self.m = cp_model.CpModel()
        n = len(self.terms)
        self.objective: List = []

        # x[c][t]: course c in term t, for the terms it is offered in
        self.x: Dict[str, Dict[int, object]] = {}
        self.placed: Dict[str, object] = {}
        self.term_of: Dict[str, object] = {}
        for code in self.courses:
            course = catalog[code]
            offered = {t for t, (_, kind) in enumerate(self.terms) if course.is_available(kind.value)}
            self.x[code] = {t: self.m.NewBoolVar(f"x_{code}_{t}") for t in sorted(offered)}
            self.placed[code] = self.m.NewBoolVar(f"placed_{code}")
            self.m.Add(sum(self.x[code].values()) == self.placed[code])
            self.term_of[code] = self.m.NewIntVar(0, max(n - 1, 0), f"term_{code}")
            self.m.Add(self.term_of[code] == sum(t * v for t, v in self.x[code].items()))
            self.objective.append(UNPLACED * (1 - self.placed[code]))

        # Plan code standing in for each code it is equivalent to
        self.plan_code: Dict[str, str] = {}
        for code in self.courses:
            for equivalent in sorted(catalog.equivalents(code)):
                self.plan_code.setdefault(equivalent, code)

        self._add_requisites()
        self._add_term_limits()
        self._add_deadlines(credit_deadlines, semester_deadlines)
        self._add_objective(electives)

    # -- requisites --------------------------------------------------------

    def _add_requisites(self) -> None:
        for code in self.courses:
            course = self.catalog[code]
            for condition in course.prerequisites:
                self._require(code, self._holds(condition, code, strict=True))
            for condition in course.corequisites:
                self._require(code, self._holds(condition, code, strict=False))

    def _require(self, code: str, holds) -> None:
        if holds is True:
            return
        if holds is False:
            self.m.Add(self.placed[code] == 0)
        else:
            self.m.AddImplication(self.placed[code], holds)

    def _holds(self, condition: PrerequisiteCondition, code: str, strict: bool):
        """A literal (or True/False) that is true when ``condition`` holds for ``code``'s term."""
        if condition.type == PrerequisiteType.COURSE:
            return self._all([self._before(p, code, strict, condition.min_grade)
                              for p in condition.courses or []])
        if condition.type == PrerequisiteType.AND:
            return self._all([self._holds(c, code, strict) for c in condition.conditions or []])
        options = [self._before(p, code, strict) for p in condition.courses or []]
        options += [self._holds(c, code, strict) for c in condition.conditions or []]
        if not options:
            return True
        return self._any(options)

    def _before(self, prerequisite: str, code: str, strict: bool,
                minimum: Optional[str] = None):
        """
        True if ``prerequisite`` (or an equivalent) is credited with at least
        ``minimum``; else a literal for "planned (or retaken) before ``code``".
        """
        if any(meets_minimum(self.grades[e], minimum)
               for e in self.catalog.equivalents(prerequisite) if e in self.grades):
            return True
        planned = self.plan_code.get(prerequisite)
        if planned is None or planned == code:
            return False
        literal = self.m.NewBoolVar(f"before_{planned}_{code}")
        self.m.AddImplication(literal, self.placed[planned])
        gap = 1 if strict else 0
        self.m.Add(self.term_of[planned] + gap <= self.term_of[code]).OnlyEnforceIf(literal)
        return literal

    def _all(self, literals):
        if any(l is False for l in literals):
            return False
        literals = [l for l in literals if l is not True]
        if not literals:
            return True
        if len(literals) == 1:
            return literals[0]
        both = self.m.NewBoolVar("all")
        self.m.AddBoolAnd(literals).OnlyEnforceIf(both)
        return both

    def _any(self, literals):
        if any(l is True for l in literals):
            return True
        literals = [l for l in literals if l is not False]
        if not literals:
            return False
        if len(literals) == 1:
            return literals[0]
        either = self.m.NewBoolVar("any")
        self.m.AddBoolOr(literals).OnlyEnforceIf(either)
        return either

    # -- terms -------------------------------------------------------------

    def _in_term(self, t: int) -> List[Tuple[str, object]]:
        return [(c, self.x[c][t]) for c in self.courses if t in self.x[c]]

    def _add_term_limits(self) -> None:
        catalog = self.catalog
        self.load: List = []
        for t, (_, kind) in enumerate(self.terms):
            in_term = self._in_term(t)
            load = self.m.NewIntVar(0, 100, f"load_{t}")
            self.m.Add(load == sum(catalog[c].credits * v for c, v in in_term))
            self.m.Add(load <= rules.credit_load(self.student, kind.value)[1])
            limit = rules.course_limit(self.student, kind.value)
            if limit is not None:
                self.m.Add(sum(v for _, v in in_term) <= limit)
            upper = [v for c, v in in_term if rules.counts_toward_upper_level_cmsc_cap(catalog[c])]
            if upper:
                self.m.Add(sum(upper) <= rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER)
            self.load.append(load)

        # Credits before each term, for courses that need prior credits (FSPW at 60)
        self.before: List = []
        running = self.student.credits_completed
        for t in range(len(self.terms)):
            cumulative = self.m.NewIntVar(0, 1000, f"credits_before_{t}")
            self.m.Add(cumulative == running + sum(self.load[:t]))
            self.before.append(cumulative)
        for code in self.courses:
            needed = rules.credits_required_before(catalog[code])
            if needed:
                for t, v in self.x[code].items():
                    self.m.Add(self.before[t] >= needed).OnlyEnforceIf(v)

    # -- deadlines ---------------------------------------------------------

    def _semester_number(self, t: int) -> int:
        """1-based Fall/Spring semester count of term ``t``; a Summer/Winter counts with the next one."""
        number = 0
        for _, kind in self.terms[:t + 1]:
            number += kind.value in rules.REGULAR_TERMS
        return number + (self.terms[t][1].value not in rules.REGULAR_TERMS)

    def _add_deadlines(self, credit_deadlines: Mapping[str, int],
                       semester_deadlines: Mapping[str, int]) -> None:
        for code in self.courses:
            late_terms = set()
            if code in semester_deadlines:
                late_terms |= {t for t in self.x[code]
                               if self._semester_number(t) > semester_deadlines[code]}
            missed = []
            for t, v in sorted(self.x[code].items()):
                if t in late_terms:
                    missed.append(v)
                elif code in credit_deadlines:
                    # Late if the credits before this term already reached the deadline
                    late = self.m.NewBoolVar(f"late_{code}_{t}")
                    self.m.Add(self.before[t] >= credit_deadlines[code]).OnlyEnforceIf(late)
                    self.m.Add(self.before[t] < credit_deadlines[code]).OnlyEnforceIf(late.Not())
                    both = self.m.NewBoolVar(f"missed_{code}_{t}")
                    self.m.AddBoolAnd([v, late]).OnlyEnforceIf(both)
                    self.m.AddBoolOr([v.Not(), late.Not()]).OnlyEnforceIf(both.Not())
                    missed.append(both)
            if missed:
                self.objective.append(MISSED_DEADLINE * sum(missed))

    # -- objective ---------------------------------------------------------

    def _add_objective(self, electives: Set[str]) -> None:
        n = len(self.terms)
        last = self.m.NewIntVar(0, max(n - 1, 0), "last_term")
        for code in self.courses:
            self.m.Add(last >= self.term_of[code])
        self.objective.append(TERM_USED * last)

        low = self.student.preferred_credit_load[0]
        regular = [t for t, (_, kind) in enumerate(self.terms) if kind.value in rules.REGULAR_TERMS]
        heaviest = self.m.NewIntVar(0, 100, "heaviest")
        lightest = self.m.NewIntVar(0, 100, "lightest")
        for t in regular:
            used = self.m.NewBoolVar(f"used_{t}")
            self.m.Add(last >= t).OnlyEnforceIf(used)
            self.m.Add(last < t).OnlyEnforceIf(used.Not())
            shortfall = self.m.NewIntVar(0, 100, f"shortfall_{t}")
            self.m.Add(shortfall >= low - self.load[t]).OnlyEnforceIf(used)
            self.objective.append(SHORTFALL * shortfall)
            self.m.Add(heaviest >= self.load[t])
            self.m.Add(lightest <= self.load[t]).OnlyEnforceIf(used)
        self.m.Add(lightest <= heaviest)
        self.objective.append(SPREAD * (heaviest - lightest))

        limit = int(round(self.student.max_difficulty_per_semester * 10))
        for t in range(n):
            in_term = self._in_term(t)
            if not in_term:
                continue
            over = self.m.NewIntVar(0, 10_000, f"difficulty_over_{t}")
            self.m.Add(over >= sum(int(round(self.catalog[c].difficulty * 10)) * v
                                   for c, v in in_term) - limit)
            self.objective.append(DIFFICULTY * over)

        for code in self.courses:
            if code not in electives:
                self.objective.append(EARLY * self.term_of[code])
        self.m.Minimize(sum(self.objective))

    # -- solving -----------------------------------------------------------

    def add_hint(self, schedule: Schedule) -> None:
        index = {(year, kind): t for t, (year, kind) in enumerate(self.terms)}
        where = {code: index.get((s.year, s.type)) for s in schedule.semesters for code in s.courses}
        for code in self.courses:
            for t, v in self.x[code].items():
                self.m.AddHint(v, int(where.get(code) == t))

    def solve(self) -> Optional[Schedule]:
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = 0
        solver.parameters.max_deterministic_time = DETERMINISTIC_TIME_LIMIT
        status = solver.Solve(self.m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        schedule = Schedule()
        for t, (year, kind) in enumerate(self.terms):
            courses = [c for c in self.courses if t in self.x[c] and solver.Value(self.x[c][t])]
            if courses:
                schedule.add_semester(Semester(year=year, type=kind, courses=courses))
        return schedule
