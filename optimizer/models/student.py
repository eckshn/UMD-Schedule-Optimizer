"""Student profile and degree program models."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Dict, Set, Tuple
import math

from .catalog import honors_pair
from .course import PrerequisiteCondition, PrerequisiteType

if TYPE_CHECKING:
    from .requirements import MajorRequirements, MinorRequirements, Requirement


@dataclass(frozen=True)
class CourseRequest:
    """
    A course the student wants to take before graduating, whether or not a
    requirement calls for it, optionally by a deadline. The deadline can be a
    required course's too: requesting it just sets when it must be taken.
    """
    code: str
    by_semester: Optional[int] = None  # by the end of the plan's Nth semester (1 = its first)
    by_credits: Optional[int] = None   # by the end of the semester cumulative credits reach this

    @property
    def deadline(self) -> str:
        """``"by semester 4"``, ``"by 60 credits"``, both, or ``"by graduation"``."""
        parts = ([f"by semester {self.by_semester}"] if self.by_semester is not None else []) + (
            [f"by {self.by_credits} credits"] if self.by_credits is not None else [])
        return " and ".join(parts) or "by graduation"


@dataclass
class StudentProfile:
    """Student's academic profile."""
    student_id: str
    name: str
    primary_major: str
    
    credits_completed: int = 0
    gpa: float = 0.0
    current_semester: int = 0  # 0-indexed (0 = first semester)
    
    completed_courses: Dict[str, str] = field(default_factory=dict)  # code -> grade
    in_progress_courses: List[str] = field(default_factory=list)
    
    ap_credits: Dict[str, str] = field(default_factory=dict)  # AP test -> course equivalency
    transfer_credits: Dict[str, str] = field(default_factory=dict)  # course code -> grade
    
    declared_minors: List[str] = field(default_factory=list)
    pending_minors: List[str] = field(default_factory=list)

    # Courses to fit into the plan (see CourseRequest); plain codes mean "by graduation"
    requested_courses: List[CourseRequest] = field(default_factory=list)
    
    preferred_credit_load: Tuple[int, int] = (15, 17)  # (min, max) credits per semester
    # Optional terms between Fall and Spring semesters, filled up to these
    # limits (credits capped by rules.MAX_TERM_CREDITS). Students usually take
    # one course in a Summer or Winter term.
    include_summer: bool = False
    include_winter: bool = False
    summer_max_courses: int = 1
    winter_max_courses: int = 1
    summer_max_credits: int = 8   # one summer session; UMD allows 8 per session
    winter_max_credits: int = 4
    max_difficulty_per_semester: float = 20.0  # Sum of difficulty ratings

    def __post_init__(self):
        self.requested_courses = [r if isinstance(r, CourseRequest) else CourseRequest(r)
                                  for r in self.requested_courses]
    
    def calculate_semesters_remaining(self, total_credits_needed: int = 120) -> int:
        """Calculate how many semesters until graduation."""
        credits_needed = total_credits_needed - self.credits_completed
        avg_credits_per_semester = sum(self.preferred_credit_load) / 2
        return math.ceil(credits_needed / avg_credits_per_semester)
    
    def credited_courses(self) -> Set[str]:
        """Course codes the student already has credit for (taken, AP or transfer)."""
        return (set(self.completed_courses)
                | set(self.ap_credits.values())
                | set(self.transfer_credits))

    def has_completed(self, course_code: str) -> bool:
        """
        Check if student has credit for a course or its honors/base counterpart
        (AAAS100H is equivalent to AAAS100). Cross-listed equivalents need the
        catalog: see ``Catalog.has_equivalent_in``.
        """
        return not honors_pair(course_code).isdisjoint(self.credited_courses())

    def get_grade(self, course_code: str) -> Optional[str]:
        """Get grade for a completed course."""
        if course_code in self.completed_courses:
            return self.completed_courses[course_code]
        elif course_code in self.ap_credits.values():
            return "P"  # Pass for AP credits
        elif course_code in self.transfer_credits:
            return self.transfer_credits.get(course_code, "P")
        return None


@dataclass(frozen=True)
class RequirementOwner:
    """
    The degree program a requirement belongs to. Courses one program applies
    can't count toward another, except a minor may share a few with a major
    (``rules.within_major_minor_overlap``).
    """
    kind: str  # "major", "minor", or "degree" for university-wide gen-eds and credit minimums
    code: str
    max_major_overlap_courses: Optional[int] = None  # a minor's own cap, if tighter than UMD's


DEGREE = RequirementOwner("degree", "degree")


@dataclass
class StudentDegreeProgram:
    """
    Student's degree program: one or more majors, any number of minors, and
    the university-wide gen-eds.
    """
    student: StudentProfile
    primary_major: 'MajorRequirements'
    additional_majors: List['MajorRequirements'] = field(default_factory=list)
    minors: List['MinorRequirements'] = field(default_factory=list)
    gen_ed_requirements: List['Requirement'] = field(default_factory=list)

    @property
    def majors(self) -> List['MajorRequirements']:
        """The primary major, then any additional majors."""
        return [self.primary_major, *self.additional_majors]
    
    def get_all_requirements(self) -> List['Requirement']:
        """Get all requirements for the degree program."""
        return [requirement for _, requirement in self.owned_requirements()]

    def owned_requirements(self) -> List[Tuple[RequirementOwner, 'Requirement']]:
        """
        Every requirement with the program it belongs to, in the order
        ``get_all_requirements`` returns them: each major, each minor, gen-eds,
        then the degree-wide credit minimums.
        """
        owned: List[Tuple[RequirementOwner, 'Requirement']] = []
        for major in self.majors:
            owner = RequirementOwner("major", major.major_code)
            parts = major.lower_level + major.upper_level + major.supporting_courses
            parts += [major.concentration] if major.concentration else []
            owned.extend((owner, r) for r in parts)
        for minor in self.minors:
            owner = RequirementOwner("minor", minor.minor_code, minor.max_overlap_with_major)
            owned.extend((owner, r) for r in
                         minor.core_courses + minor.supporting_courses + minor.electives)
        owned.extend((DEGREE, r) for r in self.gen_ed_requirements)
        # Degree-wide credit minimums count every course, so they come last
        owned.extend((DEGREE, r) for r in self.credit_requirements())
        return owned

    def credit_requirements(self) -> List['Requirement']:
        """
        The degree-wide credit minimums (``MajorRequirements.credit_requirements``):
        one per kind (``total_credits``, ``upper_level_credits``), the highest
        any major asks for.
        """
        highest: Dict[str, 'Requirement'] = {}
        for major in self.majors:
            for requirement in major.credit_requirements():
                current = highest.get(requirement.id)
                if current is None or requirement.min_credits > current.min_credits:
                    highest[requirement.id] = requirement
        return list(highest.values())

    def prerequisite_overrides(self) -> Dict[str, List[PrerequisiteCondition]]:
        """
        Course -> its prerequisites for this student, from every major's and
        minor's ``prerequisite_overrides``, to replace the catalog's
        (``Catalog.with_prerequisites``). When several programs give the same
        course different prerequisites, meeting any one program's is enough.
        """
        by_course: Dict[str, List[List[PrerequisiteCondition]]] = {}
        for program in [*self.majors, *self.minors]:
            for code, prerequisites in program.prerequisite_overrides.items():
                if prerequisites not in by_course.setdefault(code, []):
                    by_course[code].append(prerequisites)
        combined: Dict[str, List[PrerequisiteCondition]] = {}
        for code, alternatives in by_course.items():
            if len(alternatives) == 1:
                combined[code] = alternatives[0]
            else:
                combined[code] = [PrerequisiteCondition(type=PrerequisiteType.OR, conditions=[
                    PrerequisiteCondition(type=PrerequisiteType.AND, conditions=list(a))
                    for a in alternatives])]
        return combined

    def benchmark_requirements(self) -> List[Tuple[int, 'Requirement']]:
        """Every major's benchmarks, in credit order."""
        return sorted((b for m in self.majors for b in m.benchmark_requirements()),
                      key=lambda b: (b[0], b[1].id))
    
    def calculate_total_credits_needed(self) -> int:
        """Calculate total credits needed considering overlaps."""
        # Simplified - doesn't account for double counting yet
        return max(major.min_credits for major in self.majors)
