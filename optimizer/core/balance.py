"""
Even out credits across a schedule's semesters (pipeline phase 5).

The greedy assignment fills each semester up to the student's maximum load,
so plans tend to end with a light semester. ``balance_credits`` then moves
courses (or swaps two) between heavier and lighter semesters while that
brings them closer, keeping the schedule valid: prerequisites, term offerings, the
maximum load, the ``rules.py`` limits and difficulty, plus whatever the
caller's ``keeps`` check guards (benchmarks and request deadlines). It never
adds or removes semesters.
"""

from typing import Callable, Collection, List, Optional, Set

from ..models.catalog import Catalog
from ..models.schedule import Schedule
from ..models.student import StudentProfile
from . import rules


def balance_credits(schedule: Schedule, catalog: Catalog, student: StudentProfile,
                    movable_first: Collection[str] = (),
                    keeps: Optional[Callable[[Schedule], bool]] = None) -> Schedule:
    """
    Move courses between ``schedule``'s semesters, in place, until no move
    narrows the gap between a heavier and a lighter Fall/Spring semester
    (Summer and Winter terms keep their courses, though moves must keep
    theirs valid).

    A move takes a course from the heavier semester to the lighter one,
    optionally swapping in a course worth fewer credits from the lighter one
    (when a single move would break something, such as FSPW's 60 credits). The
    credits moved must be less than the difference, so the semesters only get
    closer and the loop ends. Semester pairs are tried from the largest
    difference down. Within a pair, moves of a course in ``movable_first``
    (free electives) go first, then single moves before swaps, then moves of
    a course no later course depends on, then the move that leaves the two
    semesters closest, then course codes. A move is kept only if the schedule
    stays valid (``_valid``), neither semester gets harder than the harder of
    the two and ``student.max_difficulty_per_semester``, and ``keeps`` (if
    given) still accepts it.
    """
    movable_first = set(movable_first)
    semesters = schedule.semesters
    # Only Fall/Spring semesters are evened out; Summer and Winter keep what they have
    regular = [i for i, s in enumerate(semesters) if s.type.value in rules.REGULAR_TERMS]
    max_load = student.preferred_credit_load[1]

    def credits(code: Optional[str]) -> int:
        return catalog[code].credits if code else 0

    while True:
        loads = [s.total_credits(catalog) for s in semesters]
        pairs = sorted(((h, l) for h in regular for l in regular if loads[h] > loads[l]),
                       key=lambda p: (-(loads[p[0]] - loads[p[1]]), p))
        for heavy, light in pairs:
            gap = loads[heavy] - loads[light]
            needed = _needed_later(schedule, catalog, heavy)
            outgoing = [c for c in semesters[heavy].courses if c in catalog]
            incoming = [None] + [c for c in semesters[light].courses if c in catalog]
            moves = sorted(
                ((out, back) for out in outgoing for back in incoming
                 if 0 < credits(out) - credits(back) < gap
                 and loads[light] + credits(out) - credits(back) <= max_load),
                key=lambda m: (m[0] not in movable_first, m[1] is not None,
                               m[1] is not None and m[1] not in movable_first, m[0] in needed,
                               abs(gap - 2 * (credits(m[0]) - credits(m[1]))), m[0], m[1] or ""))
            if any(_try_exchange(schedule, catalog, student, heavy, light, out, back, keeps)
                   for out, back in moves):
                break
        else:
            return schedule


def _needed_later(schedule: Schedule, catalog: Catalog, index: int) -> Set[str]:
    """Courses in semester ``index`` that a course in a later semester names as a prerequisite."""
    named: Set[str] = set()
    for semester in schedule.semesters[index + 1:]:
        for code in semester.courses:
            course = catalog.get(code)
            for condition in course.prerequisites if course else ():
                named |= _named(condition)
    return {c for c in schedule.semesters[index].courses
            if not catalog.equivalents(c).isdisjoint(named)}


def _named(condition) -> Set[str]:
    codes = set(condition.courses or [])
    for nested in condition.conditions or []:
        codes |= _named(nested)
    return codes


def _try_exchange(schedule: Schedule, catalog: Catalog, student: StudentProfile,
                  heavy: int, light: int, out: str, back: Optional[str],
                  keeps: Optional[Callable[[Schedule], bool]]) -> bool:
    """
    Move ``out`` from semester ``heavy`` to ``light`` (and ``back``, if given,
    the other way) if the result is acceptable (see ``balance_credits``);
    otherwise undo it.
    """
    pair = (schedule.semesters[heavy], schedule.semesters[light])
    before = [list(s.courses) for s in pair]
    peak = max(student.max_difficulty_per_semester, *(s.total_difficulty(catalog) for s in pair))
    pair[0].courses.remove(out)
    pair[1].courses.append(out)
    if back is not None:
        pair[1].courses.remove(back)
        pair[0].courses.append(back)
    if (all(s.total_difficulty(catalog) <= peak for s in pair)
            and _valid(schedule, catalog, student) and (keeps is None or keeps(schedule))):
        return True
    for semester, courses in zip(pair, before):
        semester.courses[:] = courses
    return False


def _valid(schedule: Schedule, catalog: Catalog, student: StudentProfile) -> bool:
    """
    Whether every planned course has its prerequisites from earlier semesters
    and its corequisites from earlier or the same semester (equivalents count,
    as in the scheduler), is offered that term, and meets
    ``rules.credits_required_before``; and every semester stays within its
    term's maximum load (``rules.credit_load``) and course count
    (``rules.course_limit``), and the upper-level CMSC cap.
    """
    completed = student.grades()  # credited courses' grades; planned ones count as an A
    cumulative = student.credits_completed
    for semester in schedule.semesters:
        upper_cmsc = 0
        concurrent = {**completed, **{e: "A" for c in semester.courses for e in catalog.equivalents(c)}}
        for code in semester.courses:
            course = catalog.get(code)
            if course is None:
                continue
            if (not course.is_available(semester.type.value)
                    or not course.prerequisites_satisfied(completed)
                    or not course.corequisites_satisfied(concurrent)
                    or cumulative < rules.credits_required_before(course)):
                return False
            upper_cmsc += rules.counts_toward_upper_level_cmsc_cap(course)
        credits = semester.total_credits(catalog)
        max_courses = rules.course_limit(student, semester.type.value)
        if (credits > rules.credit_load(student, semester.type.value)[1]
                or (max_courses is not None and len(semester.courses) > max_courses)
                or upper_cmsc > rules.MAX_UPPER_LEVEL_CMSC_PER_SEMESTER):
            return False
        for code in semester.courses:
            completed.update({e: "A" for e in catalog.equivalents(code)})
        cumulative += credits
    return True
