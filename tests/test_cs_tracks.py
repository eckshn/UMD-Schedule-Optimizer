"""Every CS specialization in sample_data/majors/CMSC.json plans and audits cleanly."""

from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentDegreeProgram, StudentProfile

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"
LOADER = DataLoader(SAMPLE_DATA)
CATALOG = LOADER.load_catalog()


def _plan(track):
    program = StudentDegreeProgram(
        student=StudentProfile(student_id="1", name=track, primary_major="CMSC"),
        primary_major=LOADER.load_major("CMSC", track),
        gen_ed_requirements=LOADER.load_gen_eds(),
    )
    optimizer = ScheduleOptimizer(CATALOG)
    schedule = optimizer.optimize_schedule(program)
    return optimizer.audit(program, schedule), schedule


def test_cmsc_defines_the_general_track_and_four_specializations():
    assert LOADER.major_tracks("CMSC") == ["general", "cybersecurity", "data_science",
                                           "machine_learning", "quantum_information"]


@pytest.mark.parametrize("track", LOADER.major_tracks("CMSC"))
def test_every_track_meets_every_requirement_in_eight_semesters(track):
    report, schedule = _plan(track)

    assert [(r.requirement.id, r.reason) for r in report.unmet] == []
    assert len(schedule.semesters) <= 8


@pytest.mark.parametrize("track", ["cybersecurity", "data_science", "machine_learning",
                                   "quantum_information"])
def test_specializations_span_three_cs_areas(track):
    report, _ = _plan(track)

    applied = report["cs_area_distribution"].applied
    assert len({CATALOG.primary_area(c) for c in applied}) >= 3
    assert all(c.startswith("CMSC4") for c in applied)


def test_specialization_specific_requirements():
    cyber, _ = _plan("cybersecurity")
    data_science, _ = _plan("data_science")
    quantum, _ = _plan("quantum_information")

    assert set(cyber["cyber_required"].applied) == {"CMSC414", "CMSC456"}
    assert len(cyber["cyber_choices"].applied) == 4
    assert data_science["statistics"].applied == ("STAT400",)  # STAT400 specifically
    assert set(quantum["qi_required"].applied) == {"CMSC457", "PHYS467"}
    outside_theory = {CATALOG.primary_area(c) for c in quantum["qi_choices"].applied} - {"Area4_Theory"}
    assert len(outside_theory) >= 2


def test_only_specializations_require_linear_algebra():
    general = LOADER.load_major("CMSC")
    ids = {r.id for r in general.supporting_courses}

    assert "linear_algebra" not in ids
    for track in ("data_science", "machine_learning", "quantum_information"):
        assert "linear_algebra" in {r.id for r in LOADER.load_major("CMSC", track).supporting_courses}
