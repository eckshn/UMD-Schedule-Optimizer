"""The Mathematics major (sample_data/majors/MATH.json) and a CS + Math double major."""

from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentDegreeProgram, StudentProfile

LOADER = DataLoader(Path(__file__).resolve().parent.parent / "sample_data")
CATALOG = LOADER.load_catalog()


def _plan(*majors, track=None):
    loaded = [LOADER.load_major(code, track if code == "MATH" else None) for code in majors]
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="t", primary_major=majors[0]),
        primary_major=loaded[0], additional_majors=loaded[1:],
        gen_ed_requirements=LOADER.load_gen_eds())
    optimizer = ScheduleOptimizer(CATALOG)
    schedule = optimizer.optimize_schedule(program)
    return optimizer.audit(program, schedule), schedule, optimizer.select_courses(program)


def test_math_defines_three_tracks():
    assert LOADER.major_tracks("MATH") == ["traditional", "statistics", "applied"]


@pytest.mark.parametrize("track", ["traditional", "statistics", "applied"])
def test_every_math_track_meets_every_requirement_in_eight_semesters(track):
    report, schedule, _ = _plan("MATH", track=track)

    assert [(r.requirement.id, r.reason) for r in report.unmet] == []
    assert len(schedule.semesters) <= 8


def test_traditional_track_has_a_sequence_and_eight_upper_level_courses():
    report, _, _ = _plan("MATH", track="traditional")

    sequence = report["math_sequence"].applied
    assert len(sequence) == 2 and "MATH410" in report["math_advanced_calculus"].applied
    upper = report["math_upper_level_courses"].applied
    assert len(upper) >= 8
    assert not {"MATH461", "STAT464"} & set(upper)


def test_statistics_track_names_its_courses():
    report, _, _ = _plan("MATH", track="statistics")

    assert report["stat_probability"].applied == ("STAT410",)
    assert report["stat_computing"].applied == ("STAT430",)
    assert len(report["stat_electives"].applied) == 2


@pytest.mark.parametrize("majors", [("CMSC", "MATH"), ("MATH", "CMSC")])
def test_cs_and_math_double_major_fits_by_sharing_courses(majors):
    report, schedule, selection = _plan(*majors)

    assert [(r.requirement.id, r.reason) for r in report.unmet] == []
    assert set(selection.courses) <= set(schedule.get_all_courses())
    assert schedule.total_credits(CATALOG) <= 124
    # Cross-listed CMSC460/AMSC460 is one course, counted by both majors
    planned = set(schedule.get_all_courses())
    assert len({"CMSC460", "AMSC460"} & planned) == 1


HONORS = {"MATH140": "A", "MATH141": "A", "MATH340": "A", "MATH341": "A"}


@pytest.mark.parametrize("track", ["traditional", "statistics", "applied"])
def test_honors_340_341_replaces_240_241_246(track):
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name="t", primary_major="MATH",
                               completed_courses=HONORS, credits_completed=16),
        primary_major=LOADER.load_major("MATH", track), gen_ed_requirements=LOADER.load_gen_eds())
    optimizer = ScheduleOptimizer(CATALOG)
    schedule = optimizer.optimize_schedule(program)
    report = optimizer.audit(program, schedule)

    assert report.unmet == []
    assert report["math_multivariable"].applied == ("MATH340",)
    assert report["math_linear_algebra"].applied == ("MATH341",)
    # No credit for the courses 340-341 replace
    assert not {"MATH240", "MATH241", "MATH246", "MATH461"} & set(schedule.get_all_courses())


def test_340_341_meet_prerequisites_naming_240_241_246():
    honors = {code: "A" for code in HONORS}

    assert CATALOG["CMSC422"].prerequisites_satisfied({"CMSC330": "A", "CMSC351": "A",
                                                       "CMSC320": "A", **honors})
    assert CATALOG["MATH410"].prerequisites_satisfied({"MATH310": "A", **honors})
