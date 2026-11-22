"""
Alternatives to a planned course (ScheduleOptimizer.course_alternatives) and
planning around courses the student excluded (StudentProfile.excluded_courses).
"""

import copy
from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(scope="module")
def loader():
    return DataLoader(SAMPLE_DATA)


@pytest.fixture(scope="module")
def optimizer(loader):
    return ScheduleOptimizer(loader.load_catalog())


def cs_program(loader, **student):
    return StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="CS", primary_major="CMSC", **student),
        primary_major=loader.load_major("CMSC"),
        gen_ed_requirements=loader.load_gen_eds(),
    )


@pytest.fixture(scope="module")
def plan(loader, optimizer):
    program = cs_program(loader)
    return program, optimizer.optimize_schedule(program)


def swapped(schedule, old, new):
    schedule = copy.deepcopy(schedule)
    for semester in schedule.semesters:
        if old in semester.courses:
            semester.courses[semester.courses.index(old)] = new
    return schedule


def test_courses_a_requirement_names_have_no_alternatives(optimizer, plan):
    program, schedule = plan

    alternatives = optimizer.course_alternatives(program, schedule, ["CMSC131", "MATH140"])

    assert alternatives == {"CMSC131": (), "MATH140": ()}


def test_each_alternative_keeps_the_plan_valid_and_complete(optimizer, plan):
    program, schedule = plan
    upper = optimizer.audit(program, schedule)["cs_400_level_total"].applied[0]

    alternatives = optimizer.course_alternatives(program, schedule, [upper])[upper]

    assert alternatives
    planned = set(schedule.get_all_courses())
    for alternative in alternatives:
        assert alternative not in planned
        changed = swapped(schedule, upper, alternative)
        assert optimizer.audit(program, changed).unmet == []
        assert optimizer.course_catalog[alternative].is_available(
            next(s for s in changed.semesters if alternative in s.courses).type.value)


def test_free_electives_can_be_swapped_for_many_courses(optimizer, plan):
    program, schedule = plan
    elective = optimizer.select_courses(program).electives[0]

    alternatives = optimizer.course_alternatives(program, schedule, [elective])[elective]

    assert len(alternatives) > 100
    assert set(alternatives).isdisjoint(schedule.get_all_courses())


def test_excluded_courses_are_not_offered_as_alternatives(loader, optimizer, plan):
    program, schedule = plan
    upper = optimizer.audit(program, schedule)["cs_400_level_total"].applied[0]
    first = optimizer.course_alternatives(program, schedule, [upper])[upper][0]
    picky = cs_program(loader, excluded_courses=[first])

    alternatives = optimizer.course_alternatives(picky, schedule, [upper])[upper]

    assert first not in alternatives


def test_unplanned_course_is_an_error(optimizer, plan):
    program, schedule = plan

    with pytest.raises(ValueError, match="CMSC999"):
        optimizer.course_alternatives(program, schedule, ["CMSC999"])


def test_excluding_a_course_and_requesting_an_alternative_replans_with_it(loader, optimizer, plan):
    program, schedule = plan
    upper = optimizer.audit(program, schedule)["cs_400_level_total"].applied[0]
    replacement = optimizer.course_alternatives(program, schedule, [upper])[upper][0]
    changed = cs_program(loader, excluded_courses=[upper], requested_courses=[replacement])

    new_schedule = optimizer.optimize_schedule(changed)

    courses = new_schedule.get_all_courses()
    assert replacement in courses and upper not in courses
    assert optimizer.audit(changed, new_schedule).unmet == []


@pytest.mark.parametrize("requirement", ["statistics", "cs_electives_upper", "gened_dshs"])
def test_selection_avoids_excluded_courses(loader, optimizer, plan, requirement):
    program, schedule = plan
    usual = optimizer.audit(program, schedule)[requirement].applied
    picky = cs_program(loader, excluded_courses=list(usual))

    selection = optimizer.select_courses(picky)

    assert set(selection.courses).isdisjoint(usual)


def test_excluded_free_electives_are_replaced(loader, optimizer):
    electives = optimizer.select_courses(cs_program(loader)).electives
    picky = cs_program(loader, excluded_courses=list(electives))

    selection = optimizer.select_courses(picky)

    assert selection.electives and set(selection.electives).isdisjoint(electives)


def test_a_course_a_requirement_names_is_taken_even_if_excluded(loader, optimizer):
    selection = optimizer.select_courses(cs_program(loader, excluded_courses=["CMSC131"]))

    assert "CMSC131" in selection.courses

