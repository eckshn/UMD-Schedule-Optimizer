"""Which courses a rule-based CATEGORY requirement accepts."""

import re

from ..models.catalog import Catalog
from ..models.requirements import Requirement


def category_matches(requirement: Requirement, code: str, catalog: Catalog) -> bool:
    """
    Whether ``code`` passes every filter ``requirement`` sets: ``pattern``,
    ``departments``, ``exclude_departments`` (which also rejects courses
    cross-listed with an excluded department), and the ``min_level``/``max_level``
    course-number range. ``single_department`` is a constraint on the set of
    applied courses, not on one course, so callers enforce it.
    """
    if requirement.pattern and not re.match(requirement.pattern, code):
        return False
    if requirement.departments and catalog.department(code) not in requirement.departments:
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
    return True
