"""Course catalog: a read-only code -> Course mapping with equivalence lookups."""

import dataclasses
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Collection, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from .course import Course, PrerequisiteCondition, PrerequisiteType


def honors_pair(code: str) -> Set[str]:
    """``code`` plus its honors/base counterpart (``AAAS100`` <-> ``AAAS100H``)."""
    return {code, code[:-1] if code.endswith('H') else code + 'H'}


class Catalog(Mapping[str, Course]):
    """
    Every available course, keyed by code. Behaves like a read-only
    ``Dict[str, Course]`` and adds course-equivalence and numbering helpers.

    Equivalent courses are honors/base pairs and cross-listed courses
    (detected by an identical course name). Courses with overlapping credit
    (``Course.credit_only_one_of``, e.g. MATH340 and MATH241) aren't the same
    course, but a student earns credit for only one of them.
    """

    def __init__(self, courses: Optional[Mapping[str, Course]] = None):
        self._courses: Dict[str, Course] = dict(courses or {})
        self._codes_by_name: Dict[str, Set[str]] = defaultdict(set)
        self._requires: Dict[Tuple[str, str], bool] = {}
        self._credit_conflicts: Dict[str, Set[str]] = defaultdict(set)
        for code, course in self._courses.items():
            if course.name:
                self._codes_by_name[course.name].add(code)
            # A course's own list pairs it with each listed course (not the listed courses
            # with each other: MATH341 overlaps MATH240 and MATH246, which don't overlap)
            for other in course.credit_only_one_of:
                if other != code:
                    self._credit_conflicts[code].add(other)
                    self._credit_conflicts[other].add(code)

    @classmethod
    def of(cls, courses: Mapping[str, Course]) -> 'Catalog':
        """``courses`` itself if it is already a Catalog, else a Catalog of it."""
        return courses if isinstance(courses, cls) else cls(courses)

    def with_prerequisites(self, prerequisites: Mapping[str, List[PrerequisiteCondition]]) -> 'Catalog':
        """
        This catalog with the given courses' prerequisites replaced (a
        program's own prerequisites, ``StudentDegreeProgram.prerequisite_overrides``).
        Codes the catalog lacks are ignored; with nothing to replace, ``self``.
        """
        replaced = {code: dataclasses.replace(self._courses[code], prerequisites=list(conditions))
                    for code, conditions in prerequisites.items() if code in self._courses}
        return Catalog({**self._courses, **replaced}) if replaced else self

    def __getitem__(self, code: str) -> Course:
        return self._courses[code]

    def __iter__(self) -> Iterator[str]:
        return iter(self._courses)

    def __len__(self) -> int:
        return len(self._courses)

    def __repr__(self) -> str:
        return f"Catalog({len(self)} courses)"

    def equivalents(self, code: str) -> Set[str]:
        """``code``, its honors/base counterpart and any course with the same name."""
        equivalents = honors_pair(code)
        course = self._courses.get(code)
        if course and course.name:
            equivalents |= self._codes_by_name[course.name]
        return equivalents

    def credit_conflicts(self, code: str) -> Set[str]:
        """Courses a student can't also earn credit for after ``code`` (and its equivalents)."""
        conflicts: Set[str] = set()
        for equivalent in self.equivalents(code):
            conflicts |= self._credit_conflicts.get(equivalent, set())
        return conflicts - self.equivalents(code)

    def has_credit_conflict_in(self, code: str, codes: Collection[str]) -> bool:
        """Whether credit for ``code`` would overlap a course in ``codes`` (or an equivalent)."""
        return any(self.has_equivalent_in(c, codes) for c in sorted(self.credit_conflicts(code)))

    def has_equivalent_in(self, code: str, codes: Collection[str]) -> bool:
        """Whether ``code`` or any of its equivalents is in ``codes``."""
        return not self.equivalents(code).isdisjoint(codes)

    def dedupe_equivalents(self, codes: Iterable[str]) -> List[str]:
        """
        Drop equivalent duplicates, keeping the first occurrence in order but
        preferring the non-honors version when both are present.
        """
        codes = list(codes)
        present = set(codes)
        result: List[str] = []
        seen: Set[str] = set()
        for code in codes:
            if code in seen or (code.endswith('H') and code[:-1] in present):
                continue
            result.append(code)
            seen |= self.equivalents(code)
        return result

    def requires(self, code: str, prerequisite: str) -> bool:
        """
        Whether every way of meeting ``code``'s prerequisites goes through
        ``prerequisite`` (or an equivalent), directly or through other courses'
        prerequisites. ``MATH410`` requires ``MATH141`` if each of its
        alternatives (``MATH240`` or ``MATH461``) does. Alternatives that aren't
        in the catalog are ignored, since nothing is known about them.
        """
        key = (code, prerequisite)
        if key not in self._requires:
            self._requires[key] = self._course_requires(code, self.equivalents(prerequisite), set())
        return self._requires[key]

    def _course_requires(self, code: str, targets: Set[str], visiting: Set[str]) -> bool:
        course = self._courses.get(code)
        if course is None or code in visiting:
            return False  # unknown course, or a prerequisite cycle
        visiting.add(code)
        result = any(self._condition_requires(c, targets, visiting) for c in course.prerequisites)
        visiting.discard(code)
        return result

    def _condition_requires(self, condition: PrerequisiteCondition, targets: Set[str],
                            visiting: Set[str]) -> bool:
        def through(code: str) -> bool:
            return code in targets or self._course_requires(code, targets, visiting)

        if condition.type == PrerequisiteType.COURSE:
            return any(through(c) for c in condition.courses or [])
        if condition.type == PrerequisiteType.OR:
            known = [c for c in condition.courses or [] if c in targets or c in self._courses]
            nested = condition.conditions or []
            return (bool(known) or bool(nested)) and all(through(c) for c in known) and all(
                self._condition_requires(c, targets, visiting) for c in nested)
        if condition.type == PrerequisiteType.AND:
            return any(self._condition_requires(c, targets, visiting) for c in condition.conditions or [])
        return False

    @staticmethod
    def course_number(code: str) -> Optional[int]:
        """The numeric part of a code (``CMSC131`` -> 131, ``CMSC498A`` -> 498), or None."""
        match = re.match(r'[A-Z]+(\d+)', code)
        return int(match.group(1)) if match else None

    @staticmethod
    def department(code: str) -> str:
        """The letter prefix of a code (``CMSC498A`` -> ``CMSC``), or "" if there is none."""
        match = re.match(r'[A-Z]+', code)
        return match.group(0) if match else ""

    def primary_area(self, code: str) -> Optional[str]:
        """
        The course's first listed area, if any, else the first area of an
        equivalent (cross-listed AMSC460 takes CMSC460's).
        """
        for equivalent in [code] + sorted(self.equivalents(code) - {code}):
            course = self._courses.get(equivalent)
            if course and course.areas:
                return course.areas[0]
        return None
