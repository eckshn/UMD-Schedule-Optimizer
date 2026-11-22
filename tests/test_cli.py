"""The command-line interface (optimizer/cli.py) and student profile files (optimizer/data/profile.py)."""

import json
from pathlib import Path

import pytest

from optimizer.cli import main
from optimizer.data.loader import DataLoader
from optimizer.data.profile import ProfileError, load_profile
from optimizer.models.schedule import SemesterType
from optimizer.models.student import CourseRequest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "sample_data"
PROFILES = sorted((ROOT / "examples" / "profiles").glob("*.json"))


@pytest.fixture(scope="module")
def loader():
    return DataLoader(SAMPLE_DATA)


@pytest.fixture(scope="module")
def catalog(loader):
    return loader.load_catalog()


def write(tmp_path, data):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data))
    return str(path)


def run(capsys, *argv):
    status = main([*argv, "--data-dir", str(SAMPLE_DATA)])
    out, err = capsys.readouterr()
    return status, out, err


# Profiles

@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_example_profiles_load(path, loader, catalog):
    profile = load_profile(path, loader, catalog)

    assert profile.program.primary_major.major_code == "CMSC"


def test_profile_fields_map_onto_the_program(loader, catalog):
    profile = load_profile({
        "name": "T", "id": 7,
        "majors": ["CMSC", {"code": "MATH", "track": "applied"}],
        "minors": ["RAS"],
        "start": "spring 2026",
        "completed_courses": {"CMSC131": "A"},
        "ap_credits": {"AP Calculus AB": "MATH140"},
        "requested_courses": ["CMSC422", {"code": "PHYS161", "by_semester": 3}],
        "excluded_courses": ["CMSC411"],
        "preferred_credit_load": [12, 15],
    }, loader, catalog)

    program, student = profile.program, profile.program.student
    assert (profile.start_year, profile.start_semester) == (2026, SemesterType.SPRING)
    assert [m.major_code for m in program.majors] == ["CMSC", "MATH"]
    assert program.additional_majors[0].track == "applied"
    assert [m.minor_code for m in program.minors] == ["RAS"]
    assert program.gen_ed_requirements
    assert (student.name, student.student_id, student.primary_major) == ("T", "7", "CMSC")
    assert student.requested_courses == [CourseRequest("CMSC422"), CourseRequest("PHYS161", by_semester=3)]
    assert student.excluded_courses == ["CMSC411"]
    assert student.preferred_credit_load == (12, 15)
    # credits_completed defaults to the credited courses' catalog credits
    assert student.credits_completed == catalog["CMSC131"].credits + catalog["MATH140"].credits


def test_additional_degrees_and_explicit_credits(loader):
    profile = load_profile({"majors": ["CMSC"], "additional_degrees": ["MATH"],
                            "credits_completed": 40}, loader)

    assert profile.program.degrees == 2
    assert profile.program.student.credits_completed == 40


@pytest.mark.parametrize("data, message", [
    ({}, "at least one major"),
    ({"majors": ["CMSC"], "nmae": "x"}, "unknown profile keys: nmae"),
    ({"majors": ["XYZ"]}, "unknown major 'XYZ'"),
    ({"majors": [{"code": "CMSC", "track": "nope"}]}, "no track 'nope'"),
    ({"majors": ["CMSC"], "minors": ["NOPE"]}, "unknown minor 'NOPE'"),
    ({"majors": ["CMSC"], "start": "2025"}, "start must look like"),
    ({"majors": ["CMSC"], "preferred_credit_load": 15}, "preferred_credit_load"),
    ({"majors": ["CMSC"], "requested_courses": [{"code": "X", "when": 1}]}, "bad requested course"),
    ({"majors": "CMSC"}, "majors must be a list"),
    ([], "a profile is a JSON object"),
])
def test_bad_profiles_are_rejected(data, message, loader, tmp_path):
    with pytest.raises(ProfileError, match=message):
        load_profile(write(tmp_path, data), loader)


def test_unreadable_profiles_are_rejected(loader, tmp_path):
    (tmp_path / "broken.json").write_text("{")

    with pytest.raises(ProfileError, match="isn't valid JSON"):
        load_profile(tmp_path / "broken.json", loader)
    with pytest.raises(ProfileError, match="can't read"):
        load_profile(tmp_path / "missing.json", loader)


# Commands

def test_plan_prints_each_semester_and_the_requirements(capsys, tmp_path):
    status, out, _ = run(capsys, "plan", write(tmp_path, {"name": "T", "majors": ["CMSC"]}),
                         "--no-solver")

    assert status == 0
    assert out.startswith("T: Computer Science")
    assert "Fall 2025  (" in out and "CMSC131" in out
    assert "requirements met." in out


def test_plan_json_lists_semesters_and_unmet_requirements(capsys, tmp_path):
    status, out, _ = run(capsys, "plan", write(tmp_path, {"majors": ["CMSC"]}),
                         "--no-solver", "--json")

    plan = json.loads(out)["plans"][0]
    assert status == 0
    assert plan["unmet"] == []
    assert plan["total_credits"] == sum(s["credits"] for s in plan["semesters"]) >= 120
    assert plan["semesters"][0]["term"] == "Fall" and plan["semesters"][0]["year"] == 2025


def test_plan_exits_1_when_a_requirement_is_unmet(capsys, tmp_path):
    # A requested course the catalog lacks leaves its request unmet
    profile = write(tmp_path, {"majors": ["CMSC"], "requested_courses": ["NOPE999"]})

    status, out, _ = run(capsys, "plan", profile, "--no-solver")

    assert status == 1
    assert "NOPE999 isn't in the catalog" in out


def test_audit_reports_credited_progress(capsys, tmp_path):
    profile = write(tmp_path, {"majors": ["CMSC"],
                               "completed_courses": {"MATH140": "A", "MATH141": "B"}})

    status, out, _ = run(capsys, "audit", profile, "--json")

    rows = {r["id"]: r for r in json.loads(out)["requirements"]}
    assert status == 0
    assert rows["math_foundation"]["satisfied"]
    assert rows["math_foundation"]["applied"] == ["MATH140", "MATH141"]
    assert not rows["total_credits"]["satisfied"]


def test_alternatives_lists_replacements(capsys, tmp_path):
    profile = write(tmp_path, {"majors": ["CMSC"]})

    status, out, _ = run(capsys, "alternatives", profile, "CMSC131", "--no-solver")

    assert status == 0
    assert out.startswith("CMSC131 (")
    assert "no alternative fits" in out


def test_alternatives_rejects_courses_not_in_the_plan(capsys, tmp_path):
    status, _, err = run(capsys, "alternatives", write(tmp_path, {"majors": ["CMSC"]}),
                         "CMSC999", "--no-solver")

    assert status == 2
    assert "not in the plan: CMSC999" in err


def test_bad_profile_exits_2_with_a_message(capsys, tmp_path):
    status, _, err = run(capsys, "plan", write(tmp_path, {"majors": ["XYZ"]}))

    assert status == 2
    assert "error:" in err and "unknown major 'XYZ'" in err


def test_audit_prints_the_readable_report(capsys, tmp_path):
    profile = write(tmp_path, {"name": "T", "majors": ["CMSC"],
                               "completed_courses": {"CMSC131": "A"}})

    status, out, _ = run(capsys, "audit", profile)

    assert status == 0
    assert out.startswith("Degree audit for T (credited courses only")
    assert "✓ " in out and "✗ " in out


def test_audit_plan_audits_a_generated_plan(capsys, tmp_path):
    status, out, _ = run(capsys, "audit", write(tmp_path, {"majors": ["CMSC"]}),
                         "--plan", "--no-solver")

    assert status == 0
    assert "(plan Fall 2025 to " in out
    assert "requirements met." in out and "✗" not in out


def test_audit_plan_json_includes_the_plan(capsys, tmp_path):
    status, out, _ = run(capsys, "audit", write(tmp_path, {"majors": ["CMSC"]}),
                         "--plan", "--no-solver", "--json")

    data = json.loads(out)
    assert status == 0
    assert data["plan"]["semesters"] and all(r["satisfied"] for r in data["requirements"])
