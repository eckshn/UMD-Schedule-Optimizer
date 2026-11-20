"""
UMD academic policy rules, defined once.

``ScheduleOptimizer`` applies these while building a schedule and
``ConstraintValidator`` re-checks them on the result. To add a rule, add a
constant or table entry here and use it from both places.
"""

import re
from typing import Dict, Tuple

from ..models.catalog import Catalog
from ..models.course import Course

# Course numbers above this are graduate courses.
MAX_UNDERGRADUATE_LEVEL = 499

# Free electives are picked at this credit value when possible.
TYPICAL_COURSE_CREDITS = 3

# At most this many upper-level (300-499) CMSC courses in one semester.
MAX_UPPER_LEVEL_CMSC_PER_SEMESTER = 3

# Gen-ed category -> cumulative credits a student needs before taking a course in it.
GEN_ED_CREDIT_PREREQUISITES: Dict[str, int] = {"FSPW": 60}

# Gen-ed category -> other categories whose courses also satisfy it.
GEN_ED_ALSO_SATISFIED_BY: Dict[str, Tuple[str, ...]] = {"DSNS": ("DSNL",)}

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


def is_independent_study(course: Course) -> bool:
    """Whether the course is independent study or experiential learning (by its name)."""
    return bool(INDEPENDENT_STUDY_NAME.search(course.name))


def credits_required_before(course: Course) -> int:
    """Cumulative credits a student must have before taking the course (0 if none)."""
    categories = [c for option in course.gen_ed_options for c in option] or course.gen_ed_categories
    return max((GEN_ED_CREDIT_PREREQUISITES.get(c, 0) for c in categories), default=0)


def gen_ed_categories_satisfying(category: str) -> Tuple[str, ...]:
    """Categories whose courses satisfy ``category``, the category itself first."""
    return (category,) + GEN_ED_ALSO_SATISFIED_BY.get(category, ())
