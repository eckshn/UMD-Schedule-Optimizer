"""
UMD academic policy rules, defined once.

``ScheduleOptimizer`` applies these while building a schedule and
``ConstraintValidator`` re-checks them on the result. To add a rule, add a
constant or table entry here and use it from both places.
"""

import re
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Tuple

from ..models.catalog import Catalog
from ..models.course import Course

if TYPE_CHECKING:
    from ..models.student import StudentProfile

# Course numbers above this are graduate courses.
MAX_UNDERGRADUATE_LEVEL = 499

# Course numbers below this (MATH003, ...) are developmental and earn no degree credit.
MIN_DEGREE_CREDIT_LEVEL = 100

# Free electives are picked at this credit value when possible.
TYPICAL_COURSE_CREDITS = 3

# Fall and Spring: the semesters every plan has. Summer and Winter are optional
# (StudentProfile.include_summer / include_winter).
REGULAR_TERMS: Tuple[str, ...] = ("Fall", "Spring")

# Most credits an undergraduate may take without their advising college's
# approval: Winter 4; Summer 8 per session, and a plan's summer covers both
# sessions (Academic Catalog, "Registration").
MAX_TERM_CREDITS: Dict[str, int] = {"Winter": 4, "Summer": 16}

# At most this many upper-level (300-499) CMSC courses in one semester.
MAX_UPPER_LEVEL_CMSC_PER_SEMESTER = 3

# Gen-ed category -> cumulative credits a student needs before taking a course in it.
GEN_ED_CREDIT_PREREQUISITES: Dict[str, int] = {"FSPW": 60}

# Gen-ed category -> categories a student must have completed a course in
# before taking a course in it: Academic Writing (ENGL101) comes before
# Professional Writing. Testudo doesn't list it as a prerequisite, so it is
# added to every such course when the catalog loads (the alternatives are the
# catalog's courses in the required category, in code order).
GEN_ED_PREREQUISITES: Dict[str, Tuple[str, ...]] = {"FSPW": ("FSAW",)}

# Course -> courses that also meet a prerequisite naming it. The honors
# sequence MATH340-341 covers MATH240-241-246, and departments generally
# accept it where those are prerequisites. Applied when catalogs load.
PREREQUISITE_SUBSTITUTES: Dict[str, Tuple[str, ...]] = {
    "MATH240": ("MATH341",),
    "MATH241": ("MATH340",),
    "MATH246": ("MATH341",),
}

# Gen-ed category -> other categories whose courses also satisfy it.
GEN_ED_ALSO_SATISFIED_BY: Dict[str, Tuple[str, ...]] = {"DSNS": ("DSNL",)}

# Which programs may count a course another program already counts, as
# (program kind that has it, program kind that wants it). Majors may overlap
# with each other ("overlap with the electives may be permitted where
# appropriate"); a minor may share a few courses with its majors; one minor's
# courses can't count toward another minor.
MAY_SHARE = {("major", "major"), ("major", "minor")}

# UMD minor policy: "a maximum of six credits (or two courses)" may count
# toward both a major and a minor, per minor across all its majors. Read as a
# credit cap of six, or of the two largest shared courses when they're worth
# more (two 4-credit courses). A minor may also cap the number of courses
# (``MinorRequirements.max_overlap_with_major``).
MAX_MAJOR_MINOR_OVERLAP_CREDITS = 6
MAX_MAJOR_MINOR_OVERLAP_COURSES = 2

# Course names that mark independent study or experiential learning. The
# catalog has no flag for it, so this goes by name ("Experiential Learning",
# "Internship Practicum", "Directed Readings in ...", "Honors Thesis").
INDEPENDENT_STUDY_NAME = re.compile(
    r"\b(independent (study|research)|experiential learning|internship|practicum"
    r"|directed (readings?|research|study)|special problems|thesis)\b",
    re.IGNORECASE,
)


def counts_toward_upper_level_cmsc_cap(course: Course) -> bool:
    """Whether the course is a 300-499 CMSC course, limited per semester."""
    number = Catalog.course_number(course.code)
    return course.code.startswith("CMSC") and number is not None and 300 <= number < 500


def is_undergraduate(course: Course) -> bool:
    """Whether the course is numbered 499 or below."""
    number = Catalog.course_number(course.code)
    return number is not None and number <= MAX_UNDERGRADUATE_LEVEL


def earns_degree_credit(course: Course) -> bool:
    """Whether the course is an undergraduate course numbered 100 or above (not developmental)."""
    number = Catalog.course_number(course.code)
    return is_undergraduate(course) and number >= MIN_DEGREE_CREDIT_LEVEL


def is_independent_study(course: Course) -> bool:
    """Whether the course is independent study or experiential learning (by its name)."""
    return bool(INDEPENDENT_STUDY_NAME.search(course.name))


def plan_terms(student: "StudentProfile") -> Tuple[str, ...]:
    """The term types a student's plan uses: Fall and Spring, plus Summer/Winter if enabled."""
    return (REGULAR_TERMS + (("Summer",) if student.include_summer else ())
            + (("Winter",) if student.include_winter else ()))


def terms_offered(course: Course, student: "StudentProfile") -> List[str]:
    """The term types ``course`` is offered in that the student's plan uses."""
    terms = plan_terms(student)
    return [t for t in course.offered if t in terms]


def credit_load(student: "StudentProfile", term: str) -> Tuple[int, int]:
    """
    (min, max) credits for a ``term`` ("Fall", "Summer", ...): the student's
    ``preferred_credit_load`` for Fall and Spring; for Summer and Winter, no
    minimum and their max credits, capped by ``MAX_TERM_CREDITS``.
    """
    if term == "Summer":
        return 0, min(student.summer_max_credits, MAX_TERM_CREDITS["Summer"])
    if term == "Winter":
        return 0, min(student.winter_max_credits, MAX_TERM_CREDITS["Winter"])
    return student.preferred_credit_load


def course_limit(student: "StudentProfile", term: str) -> Optional[int]:
    """Most courses in a ``term``: the student's Summer/Winter limit, None for Fall and Spring."""
    return {"Summer": student.summer_max_courses,
            "Winter": student.winter_max_courses}.get(term)


def credits_required_before(course: Course) -> int:
    """Cumulative credits a student must have before taking the course (0 if none)."""
    categories = [c for option in course.gen_ed_options for c in option] or course.gen_ed_categories
    return max((GEN_ED_CREDIT_PREREQUISITES.get(c, 0) for c in categories), default=0)


def may_share(has_it: str, wants_it: str) -> bool:
    """Whether a program of kind ``wants_it`` may count a course a ``has_it`` program counts."""
    return (has_it, wants_it) in MAY_SHARE


def overlap_is_limited(kind: str) -> bool:
    """Whether a program of ``kind`` may share only a limited number of courses (minors)."""
    return kind == "minor"


def within_overlap_limit(kind: str, shared: Iterable[str], catalog: Mapping[str, Course],
                         max_courses: Optional[int] = None) -> bool:
    """
    Whether a program of ``kind`` may count every course in ``shared``
    (courses another program counted first): minors are limited by
    ``within_major_minor_overlap``; majors aren't limited.
    """
    if overlap_is_limited(kind):
        return within_major_minor_overlap(shared, catalog, max_courses)
    return True


def within_major_minor_overlap(shared: Iterable[str], catalog: Mapping[str, Course],
                               max_courses: Optional[int] = None) -> bool:
    """
    Whether a minor may count all of ``shared`` (courses a major also counts):
    their credits may total at most ``MAX_MAJOR_MINOR_OVERLAP_CREDITS`` or the
    credits of the ``MAX_MAJOR_MINOR_OVERLAP_COURSES`` largest of them,
    whichever is more (3+3 or 2+2+2 credits pass, 4+4 passes, 3+3+2 doesn't),
    and number at most ``max_courses`` when the minor sets it.
    """
    credits = sorted((catalog[c].credits for c in shared if c in catalog), reverse=True)
    if max_courses is not None and len(credits) > max_courses:
        return False
    largest = sum(credits[:MAX_MAJOR_MINOR_OVERLAP_COURSES])
    return sum(credits) <= max(MAX_MAJOR_MINOR_OVERLAP_CREDITS, largest)


def gen_ed_categories_satisfying(category: str) -> Tuple[str, ...]:
    """Categories whose courses satisfy ``category``, the category itself first."""
    return (category,) + GEN_ED_ALSO_SATISFIED_BY.get(category, ())
