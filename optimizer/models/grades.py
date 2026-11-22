"""
UMD grades: which earn credit and which meet a minimum grade.

Kept with the models (``PrerequisiteCondition`` needs it) rather than in
``core/rules.py``, which imports the models.
"""

from typing import Optional

# Letter grades and their quality points
GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "D-": 0.7,
    "F": 0.0,
}

# Passing grades without a letter: pass, satisfactory, credit, transfer credit.
# Assumed to meet any minimum (AP credit is recorded as "P" and satisfies
# prerequisites).
PASSING_WITHOUT_LETTER = {"P", "S", "CR", "TR"}

# The lowest letter grade that earns credit
LOWEST_PASSING = "D-"


def earns_credit(grade: Optional[str]) -> bool:
    """
    Whether a course taken with ``grade`` earns credit: D- or better, or a
    passing grade without a letter. F, W (withdrawn), I (incomplete), NG and
    other marks don't. No grade at all counts as passing (unknown).
    """
    return grade is None or meets_minimum(grade, LOWEST_PASSING)


def meets_minimum(grade: Optional[str], minimum: Optional[str]) -> bool:
    """
    Whether ``grade`` is at least ``minimum`` (``"C-"``). Without a minimum,
    any grade that earns credit does. ``grade`` None means unknown and passes.
    """
    if grade is None:
        return True
    grade = grade.strip().upper()
    if grade in PASSING_WITHOUT_LETTER:
        return True
    if grade not in GRADE_POINTS:
        return False
    return GRADE_POINTS[grade] >= GRADE_POINTS[(minimum or LOWEST_PASSING).strip().upper()]


def grade_rank(grade: Optional[str]) -> float:
    """Orders grades from worst to best: letters by points, then passing grades without a letter."""
    grade = (grade or "").strip().upper()
    if grade in PASSING_WITHOUT_LETTER or not grade:
        return 5.0
    return GRADE_POINTS.get(grade, -1.0)
