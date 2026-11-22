"""The human-readable audit report (optimizer/report.py)."""

from pathlib import Path

import pytest

from optimizer.core.audit import AuditReport
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.data.profile import load_profile
from optimizer.report import format_audit

ROOT = Path(__file__).resolve().parent.parent
JUNIOR = ROOT / "examples" / "profiles" / "cs_junior_ras.json"


@pytest.fixture(scope="module")
def setup():
    loader = DataLoader(ROOT / "sample_data")
    catalog = loader.load_catalog()
    return loader, catalog, ScheduleOptimizer(catalog, use_solver=False)


def junior(setup):
    loader, catalog, _ = setup
    return load_profile(JUNIOR, loader, catalog).program


def test_credited_only_report_shows_whats_met_and_whats_missing(setup):
    _, catalog, optimizer = setup
    program = junior(setup)

    text = format_audit(program, optimizer.audit(program), catalog)

    assert text.startswith("Degree audit for CS junior with a Robotics minor (credited courses only, 55 credits earned)")
    sections = [line for line in text.splitlines() if line and not line.startswith(" ")][2:]
    assert sections == ["Computer Science - General Track (major)",
                        "Robotics and Autonomous Systems (minor)", "General education",
                        "Degree", "Requested courses"]
    assert "  Limited-enrollment benchmarks" in text
    assert "✓ CS Lower Level Core\n      CMSC131 (A), CMSC132 (B+), CMSC216 (B), CMSC250 (A-)" in text
    assert "✗ Introduction to Robotics\n      Missing: ENME480" in text
    assert "✗ CS 400-Level Courses" in text and "Could take: CMSC411," in text
    assert "Why: needs 5 courses, has 0" in text
    assert "✗ 120 total credits: 55 of 120 credits" in text
    assert "Area 1" not in text  # groups that ask for nothing are left out


def test_plan_report_shows_when_each_course_is_taken(setup):
    _, catalog, optimizer = setup
    program = junior(setup)
    schedule = optimizer.optimize_schedule(program, 2027)
    report = optimizer.audit(program, schedule)

    text = format_audit(program, report, catalog, schedule)

    first, last = schedule.semesters[0], schedule.semesters[-1]
    assert f"(plan {first} to {last}," in text.splitlines()[0]
    rows = len([r for r in report.results if not (r.requirement.min_courses == 0)])
    assert f"{rows} of {rows} requirements met." in text
    assert f"ENME480 ({next(s for s in schedule.semesters if 'ENME480' in s.courses)})" in text
    assert "Missing" not in text and "Why" not in text


def test_ap_and_transfer_credit_are_labelled(setup):
    loader, catalog, optimizer = setup
    program = load_profile({"majors": ["CMSC"], "ap_credits": {"AP Calculus AB": "MATH140"},
                            "transfer_credits": {"MATH141": "TR"}}, loader, catalog).program

    text = format_audit(program, optimizer.audit(program), catalog)

    assert "MATH140 (AP), MATH141 (transfer)" in text


def test_unique_credits_appear_under_degree(setup):
    loader, catalog, optimizer = setup
    program = load_profile({"majors": ["CMSC"], "additional_degrees": ["MATH"]},
                           loader, catalog).program

    text = format_audit(program, optimizer.audit(program), catalog)

    degree = text.split("\nDegree\n")[1]
    assert "150 total credits (2 degrees)" in degree
    assert "CMSC credits no other degree's major counts" in degree
    assert "Mathematics" in text.split("\nDegree\n")[0]


def test_report_needs_a_row_per_requirement(setup):
    _, catalog, _ = setup

    with pytest.raises(ValueError, match="fewer rows"):
        format_audit(junior(setup), AuditReport(()), catalog)
