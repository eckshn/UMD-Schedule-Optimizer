"""Course catalog: a read-only code -> Course mapping with equivalence lookups."""

import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Collection, Dict, Iterable, Iterator, List, Optional, Set

from .course import Course


def honors_pair(code: str) -> Set[str]:
    """``code`` plus its honors/base counterpart (``AAAS100`` <-> ``AAAS100H``)."""
    return {code, code[:-1] if code.endswith('H') else code + 'H'}


class Catalog(Mapping[str, Course]):
    """
    Every available course, keyed by code. Behaves like a read-only
    ``Dict[str, Course]`` and adds course-equivalence and numbering helpers.

    Equivalent courses are honors/base pairs and cross-listed courses
    (detected by an identical course name).
    """

    def __init__(self, courses: Optional[Mapping[str, Course]] = None):
        self._courses: Dict[str, Course] = dict(courses or {})
        self._codes_by_name: Dict[str, Set[str]] = defaultdict(set)
        for code, course in self._courses.items():
            if course.name:
                self._codes_by_name[course.name].add(code)

    @classmethod
    def of(cls, courses: Mapping[str, Course]) -> 'Catalog':
        """``courses`` itself if it is already a Catalog, else a Catalog of it."""
        return courses if isinstance(courses, cls) else cls(courses)

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
        """The course's first listed area, if any."""
        course = self._courses.get(code)
        return course.areas[0] if course and course.areas else None
