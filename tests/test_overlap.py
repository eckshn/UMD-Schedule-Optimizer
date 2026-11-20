"""Tests for courses counting toward more than one program (majors and minors)."""

from optimizer.core import rules
from optimizer.core.audit import audit_requirements
from optimizer.core.claims import ClaimLedger
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course
from optimizer.models.requirements import (EligibilityRequirement, MajorRequirements,
                                           MinorRequirements, Requirement, RequirementType)
from optimizer.models.student import RequirementOwner, StudentDegreeProgram, StudentProfile

MAJOR = RequirementOwner("major", "MAJ")
OTHER_MAJOR = RequirementOwner("major", "MAJ2")
MINOR = RequirementOwner("minor", "MIN")
OTHER_MINOR = RequirementOwner("minor", "MIN2")


def _catalog(*codes, credits=3):
    return Catalog({code: Course(code=code, name=code, credits=credits) for code in codes})


def _course(code):
    return Requirement(id=code, name=code, type=RequirementType.COURSE, course_code=code)


def _group(id, codes, **kwargs):
    return Requirement(id=id, name=id, type=RequirementType.GROUP, courses=list(codes), **kwargs)


def _major(code, *requirements, **kwargs):
    return MajorRequirements(major_code=code, major_name=code, lower_level=list(requirements),
                             **{"min_credits": 0, **kwargs})


def _minor(code, *requirements, max_overlap=None):
    return MinorRequirements(minor_code=code, minor_name=code, department="",
                             eligibility=EligibilityRequirement(),
                             core_courses=list(requirements), max_overlap_with_major=max_overlap)


def _program(majors, minors=()):
    student = StudentProfile(student_id="1", name="T", primary_major=majors[0].major_code)
    return StudentDegreeProgram(student=student, primary_major=majors[0],
                                additional_majors=list(majors[1:]), minors=list(minors))


def test_overlap_limit_is_six_credits_or_the_two_largest_courses():
    catalog = {**_catalog("A", "B", "C"), **_catalog("BIG", "BIG2", credits=4),
               **_catalog("S1", "S2", "S3", credits=2)}

    def ok(*codes, **kwargs):
        return rules.within_major_minor_overlap(codes, catalog, **kwargs)

    assert ok("A", "B")                    # 3 + 3
    assert ok("BIG", "BIG2")               # 4 + 4: the two largest courses
    assert ok("A", "BIG")                  # 3 + 4
    assert ok("S1", "S2", "S3")            # 2 + 2 + 2: six credits
    assert not ok("A", "B", "S1")          # 3 + 3 + 2
    assert not ok("A", "B", "C")
    assert not ok("A", "B", max_courses=1)


def test_ledger_lets_a_minor_share_a_majors_course_once():
    ledger = ClaimLedger(_catalog("A", "B", "C"))
    for code in ("A", "B", "C"):
        ledger.claim(code, MAJOR)

    assert not ledger.can_claim("A", MAJOR)        # no double counting within a program
    assert not ledger.can_claim("A", OTHER_MAJOR)  # nor between two majors
    assert ledger.can_claim("A", MINOR)
    ledger.claim("A", MINOR)
    assert not ledger.can_claim("A", OTHER_MINOR)  # a minor's course can't count toward another
    ledger.claim("B", MINOR)
    assert not ledger.can_claim("C", MINOR)        # 9 credits is over the limit
    assert ledger.shared(MINOR) == ("A", "B")


def test_minors_never_share_with_each_other():
    ledger = ClaimLedger(_catalog("A"))
    ledger.claim("A", MINOR)

    assert not ledger.can_claim("A", OTHER_MINOR)
    assert not ledger.can_claim("A", MAJOR)


def test_audit_lets_a_minor_share_up_to_two_major_courses():
    catalog = _catalog("A", "B", "C")
    requirements = [_group("major", ["A", "B", "C"]), _group("minor", ["A", "B", "C"])]

    shared = audit_requirements(["A", "B", "C"], requirements, catalog, owners=[MAJOR, MINOR])
    unowned = audit_requirements(["A", "B", "C"], requirements, catalog)

    assert shared["major"].satisfied
    assert shared["minor"].applied == ("A", "B")
    assert "over the overlap limit" in shared["minor"].reason
    assert unowned["minor"].reason.startswith("missing A (counted toward major)")


def test_audit_spends_overlap_only_when_a_minor_needs_it():
    catalog = _catalog("A", "B", "X", "Y")
    major = _group("major", ["A", "B"])
    minor = _group("minor", ["A", "B", "X", "Y"], min_courses=3)

    report = audit_requirements(["A", "B", "X", "Y"], [major, minor], catalog,
                                owners=[MAJOR, MINOR])

    assert report["minor"].satisfied and report["minor"].applied == ("X", "Y", "A")


def test_minor_cap_can_be_lower_than_the_university_cap():
    catalog = _catalog("A", "B")
    requirements = [_group("major", ["A", "B"]), _group("minor", ["A", "B"])]
    capped = RequirementOwner("minor", "MIN", max_major_overlap_courses=1)

    report = audit_requirements(["A", "B"], requirements, catalog, owners=[MAJOR, capped])

    assert report["minor"].applied == ("A",) and not report["minor"].satisfied


def test_selection_shares_major_courses_with_a_minor_instead_of_adding_courses():
    catalog = _catalog("A", "B", "C", "X")
    program = _program([_major("MAJ", _group("core", ["A", "B", "C"]))],
                       [_minor("MIN", _group("pick", ["A", "B", "C", "X"], min_courses=3))])
    optimizer = ScheduleOptimizer(catalog)

    selection = optimizer.select_courses(program)

    # Two shared courses (the cap), plus one the minor adds
    assert selection.courses == ("A", "B", "C", "X")
    assert selection.by_requirement[(1,)] == ("A", "B", "X")
    assert optimizer.audit(program, optimizer.optimize_schedule(program)).satisfied


def test_major_picks_courses_a_later_minor_lists():
    catalog = _catalog("A", "B", "M")
    program = _program([_major("MAJ", _group("major_pick", ["A", "B", "M"], min_courses=1))],
                       [_minor("MIN", _course("M"))])

    selection = ScheduleOptimizer(catalog).select_courses(program)

    assert selection.courses == ("M",)


def test_second_minor_cannot_reuse_the_first_minors_course():
    catalog = _catalog("A", "B")
    program = _program([_major("MAJ")],
                       [_minor("MIN", _group("one", ["A", "B"], min_courses=1)),
                        _minor("MIN2", _group("two", ["A", "B"], min_courses=1))])
    optimizer = ScheduleOptimizer(catalog)

    selection = optimizer.select_courses(program)

    assert selection.by_requirement[(0,)] == ("A",) and selection.by_requirement[(1,)] == ("B",)
    assert optimizer.audit(program, optimizer.optimize_schedule(program)).satisfied


def test_any_number_of_majors_each_need_their_own_courses():
    catalog = _catalog("A", "B", "C")
    majors = [_major(f"MAJ{i}", _group(f"pick{i}", ["A", "B", "C"], min_courses=1))
              for i in range(3)]
    program = _program(majors)
    optimizer = ScheduleOptimizer(catalog)

    selection = optimizer.select_courses(program)

    assert [selection.by_requirement[(i,)] for i in range(3)] == [("A",), ("B",), ("C",)]
    assert optimizer.audit(program, optimizer.optimize_schedule(program)).satisfied


def test_degree_credit_minimums_take_the_highest_any_major_sets():
    program = _program([_major("MAJ", min_credits=120, min_upper_level_credits=30),
                        _major("MAJ2", min_credits=124, min_upper_level_credits=24)])

    minimums = {r.id: r.min_credits for r in program.credit_requirements()}

    assert minimums == {"total_credits": 124, "upper_level_credits": 30}
    assert [r.id for r in program.get_all_requirements()] == ["total_credits", "upper_level_credits"]


def test_benchmarks_come_from_every_major():
    program = _program([_major("MAJ", benchmarks={45: [_course("A")]}),
                        _major("MAJ2", benchmarks={30: [_course("B")]})])

    assert [r.id for _, r in program.benchmark_requirements()] == ["MAJ2_benchmark_30",
                                                                    "MAJ_benchmark_45"]
