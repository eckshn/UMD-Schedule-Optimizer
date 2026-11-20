"""
Rule-based requirements: which courses a CATEGORY or CREDIT_HOURS requirement
accepts, and how many credits count toward a CREDIT_HOURS one. Shared by the
selector and the audit.
"""

import re
from typing import Iterable, List, Tuple

from ..models.catalog import Catalog
from ..models.requirements import Requirement
from ..models.student import StudentProfile
from . import rules


_FILTERS = ("pattern", "departments", "exclude_departments", "min_level", "max_level",
            "has_prerequisite")


def has_filters(requirement: Requirement) -> bool:
    """Whether ``requirement`` sets any course filter (else every course matches)."""
    return any(getattr(requirement, name) not in (None, "", []) for name in _FILTERS)


def category_matches(requirement: Requirement, code: str, catalog: Catalog,
                     equivalents: bool = True) -> bool:
    """
    Whether ``code`` passes every filter ``requirement`` sets: ``pattern`` and
    ``departments`` (met by the course or any course cross-listed with it),
    ``exclude_departments`` (which also rejects courses cross-listed with an
    excluded department), the ``min_level``/``max_level``
    course-number range, and ``has_prerequisite`` (``Catalog.requires``). ``single_department`` is a constraint on the set of
    applied courses, not on one course, so callers enforce it.
    """
    # A cross-listed course counts in each of its departments (AMSC460 = CMSC460)
    codes = sorted(catalog.equivalents(code)) if equivalents and code in catalog else [code]
    if requirement.pattern and not any(re.match(requirement.pattern, c) for c in codes):
        return False
    if requirement.departments and not any(catalog.department(c) in requirement.departments
                                           for c in codes):
        return False
    if requirement.exclude_departments:
        excluded = set(requirement.exclude_departments)
        if any(catalog.department(c) in excluded for c in catalog.equivalents(code)):
            return False
    if requirement.min_level is not None or requirement.max_level is not None:
        number = catalog.course_number(code)
        if number is None:
            return False
        if requirement.min_level is not None and number < requirement.min_level:
            return False
        if requirement.max_level is not None and number > requirement.max_level:
            return False
    if requirement.has_prerequisite and not catalog.requires(code, requirement.has_prerequisite):
        return False
    return True


def within_limits(requirement: Requirement, applied: Iterable[str], code: str,
                  catalog: Catalog) -> bool:
    """
    Whether adding ``code`` to the courses already ``applied`` toward a
    CATEGORY keeps it within ``max_independent_study_credits``
    (``rules.is_independent_study``). Like ``single_department``, this limits
    the set of applied courses, so the selector and the audit both check it.
    """
    cap = requirement.max_independent_study_credits
    if cap is None or not rules.is_independent_study(catalog[code]):
        return True
    used = sum(catalog[c].credits for c in applied if rules.is_independent_study(catalog[c]))
    return used + catalog[code].credits <= cap


def credit_hours(requirement: Requirement, courses: Iterable[str], catalog: Catalog,
                 prior_credits: int = 0) -> Tuple[List[str], int]:
    """
    The courses counting toward a CREDIT_HOURS requirement and their credits.
    ``courses`` must already be free of equivalent duplicates. ``prior_credits``
    (credits from courses that aren't listed) count only when the requirement
    has no filters, since nothing is known about those courses.
    """
    counted = [c for c in courses if category_matches(requirement, c, catalog)]
    credits = sum(catalog[c].credits for c in counted if c in catalog)
    if not has_filters(requirement):
        credits += prior_credits
    return counted, credits


def prior_credits(student: StudentProfile, catalog: Catalog) -> int:
    """
    Credits the student has earned beyond the credited courses the catalog
    knows: ``credits_completed`` is their total, so this covers transfer or
    unlisted courses.
    """
    credited = catalog.dedupe_equivalents(sorted(student.credited_courses()))
    known = sum(catalog[c].credits for c in credited if c in catalog)
    return max(0, student.credits_completed - known)
