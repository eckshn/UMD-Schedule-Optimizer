"""Tests for loading requirement files and validating requirements."""

import json
from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.requirements import Requirement, RequirementType
from optimizer.models.student import StudentProfile, StudentDegreeProgram

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _by_id(reqs):
    return {r.id: r for r in reqs}


def test_load_cmsc_major():
    major = DataLoader(SAMPLE_DATA).load_major("CMSC")

    assert major is not None
    assert major.major_code == "CMSC"
    assert major.min_credits == 120
    assert major.min_major_credits == 0  # UMD sets no CS major-credit minimum
    assert sorted(major.benchmarks) == [45, 75]
    assert [r.course_code for r in major.benchmarks[45]] == ["CMSC131", "CMSC132", "MATH140"]
    assert major.benchmarks[75][2].type == RequirementType.CATEGORY

    lower = _by_id(major.lower_level)
    assert lower["cs_core_lower"].type == RequirementType.GROUP
    assert lower["cs_core_lower"].courses == ["CMSC131", "CMSC132", "CMSC216", "CMSC250"]
    assert lower["cs_core_lower"].min_courses == 4

    upper = _by_id(major.upper_level)
    assert upper["cs_400_level_total"].min_areas == 3
    assert upper["cs_400_level_total"].max_from_same_area == 3

    supporting = _by_id(major.supporting_courses)
    assert supporting["statistics"].type == RequirementType.CATEGORY
    assert supporting["statistics"].departments == ["STAT"]
    assert supporting["statistics"].has_prerequisite == "MATH141"

    # Gen-eds are university-wide and live in gen_eds/UMD.json, not in the major
    all_major_reqs = major.lower_level + major.upper_level + major.supporting_courses
    assert all(r.type != RequirementType.GEN_ED for r in all_major_reqs)


def test_load_umd_gen_eds():
    gen_eds = DataLoader(SAMPLE_DATA).load_gen_eds()

    assert all(r.type == RequirementType.GEN_ED for r in gen_eds)
    assert [r.gen_ed_category for r in gen_eds] == [
        "FSAW", "FSOC", "FSPW", "DSNL", "DSNS", "DSHS", "DSHU", "DSSP", "DVUP",
    ]
    dsns = _by_id(gen_eds)["gened_dsns"]
    assert (dsns.min_credits, dsns.min_courses) == (7, 2)


def test_load_ras_minor():
    minor = DataLoader(SAMPLE_DATA).load_minor("RAS")

    assert minor is not None
    assert minor.minor_code == "RAS"
    assert minor.min_credits == 21
    assert minor.fixed_schedule is True

    assert minor.eligibility.min_gpa == 3.0
    assert minor.eligibility.min_credits_completed == 30
    assert "CMSC" in minor.eligibility.allowed_majors
    assert ["MATH246", "ENES221"] in minor.eligibility.prerequisite_courses

    # RAS students' own prerequisites, with substitutes added like the catalog's
    linear_algebra, lab = minor.prerequisite_overrides["CMSC477"]
    assert "MATH461" in linear_algebra.courses and lab.courses == ["ENEE467"]

    # {"code": ...} shorthand becomes a COURSE requirement
    assert [r.course_code for r in minor.core_courses] == ["ENME480", "ENAE450", "ENEE467", "CMSC477"]
    assert all(r.type == RequirementType.COURSE for r in minor.core_courses)

    (math_req,) = minor.supporting_courses
    assert math_req.type == RequirementType.CHOICE
    assert "MATH240" in math_req.choices

    (electives,) = minor.electives
    assert electives.min_courses == 2


def test_nested_requirements(tmp_path):
    (tmp_path / "majors").mkdir()
    (tmp_path / "majors" / "TEST.json").write_text(json.dumps({
        "major_code": "TEST",
        "major_name": "Test Major",
        "lower_level": [{
            "id": "outer",
            "name": "Outer",
            "type": "group",
            "courses": [
                "AAA100",
                {"id": "inner", "name": "Inner", "type": "choice", "choices": ["BBB100", "CCC100"]},
            ],
        }],
    }))

    major = DataLoader(tmp_path).load_major("TEST")
    outer = major.lower_level[0]

    assert outer.courses[0] == "AAA100"
    inner = outer.courses[1]
    assert isinstance(inner, Requirement)
    assert inner.type == RequirementType.CHOICE
    assert inner.choices == ["BBB100", "CCC100"]


def test_missing_files_return_none(tmp_path):
    loader = DataLoader(tmp_path)
    assert loader.load_major("NOPE") is None
    assert loader.load_minor("NOPE") is None
    assert loader.load_gen_eds("NOPE") == []


@pytest.mark.parametrize("req_type, field", [
    (RequirementType.COURSE, "course_code"),
    (RequirementType.CHOICE, "choices"),
    (RequirementType.GROUP, "courses"),
    (RequirementType.GEN_ED, "gen_ed_category"),
])
def test_requirement_missing_required_field_raises(req_type, field):
    with pytest.raises(ValueError, match=f"{req_type.value} requirement 'bad' must set {field}"):
        Requirement(id="bad", name="Bad", type=req_type)


def test_requirement_validation_edge_cases(tmp_path):
    # A GROUP may be an empty placeholder
    Requirement(id="ulc", name="ULC", type=RequirementType.GROUP, courses=[], min_credits=12)
    # Extra fields are fine
    Requirement(id="c", name="C", type=RequirementType.COURSE, course_code="MATH240", min_credits=4)
    with pytest.raises(ValueError):
        Requirement(id="c", name="C", type=RequirementType.CHOICE, choices=[])
    with pytest.raises(ValueError, match="credit_hours requirement 'ch' must set min_credits"):
        Requirement(id="ch", name="Ch", type=RequirementType.CREDIT_HOURS)
    # A CATEGORY needs a quantity, or it would be met by nothing at all
    with pytest.raises(ValueError, match="category requirement 'cat' must set min_courses or min_credits"):
        Requirement(id="cat", name="Cat", type=RequirementType.CATEGORY, min_level=300)
    # Loader surfaces the same error for a malformed file entry
    (tmp_path / "gen_eds").mkdir()
    (tmp_path / "gen_eds" / "BAD.json").write_text(json.dumps({"requirements": [{"id": "x", "type": "gen_ed"}]}))
    with pytest.raises(ValueError, match="gen_ed requirement 'x' must set gen_ed_category"):
        DataLoader(tmp_path).load_gen_eds("BAD")


def test_optimizer_runs_on_loaded_major():
    loader = DataLoader(SAMPLE_DATA)
    major = loader.load_major("CMSC")
    student = StudentProfile(student_id="1", name="Test", primary_major="CMSC")
    program = StudentDegreeProgram(student=student, primary_major=major,
                                   gen_ed_requirements=loader.load_gen_eds())

    schedule = ScheduleOptimizer(loader.load_all_courses()).optimize_schedule(program)

    assert 0 < len(schedule.semesters) <= 8
    core = {"CMSC131", "CMSC132", "CMSC216", "CMSC250", "CMSC330", "CMSC351",
            "MATH140", "MATH141", "MATH240", "STAT400"}
    assert core <= set(schedule.get_all_courses())


def _write_major(tmp_path, data):
    (tmp_path / "majors").mkdir()
    (tmp_path / "majors" / "TEST.json").write_text(json.dumps(data))
    return DataLoader(tmp_path)


def test_track_requirements_replace_by_id_and_append(tmp_path):
    loader = _write_major(tmp_path, {
        "major_code": "TEST", "major_name": "Test",
        "lower_level": [{"code": "A"}, {"id": "stat", "type": "group", "courses": ["S1", "S2"],
                                        "min_courses": 1}],
        "concentration": {"id": "conc", "type": "group", "courses": ["C"]},
        "default_track": "one",
        "tracks": {
            "one": {"major_name": "Test - One"},
            "two": {"major_name": "Test - Two",
                    "lower_level": [{"id": "stat", "type": "course", "course_code": "S2"},
                                    {"code": "B"}]},
        },
    })

    one, two = loader.load_major("TEST"), loader.load_major("TEST", "two")

    assert (one.track, one.major_name) == ("one", "Test - One")
    assert [r.id for r in one.lower_level] == ["A", "stat"]
    assert two.track == "two"
    assert [(r.id, r.type) for r in two.lower_level] == [
        ("A", RequirementType.COURSE), ("stat", RequirementType.COURSE), ("B", RequirementType.COURSE)]
    assert two.concentration.id == "conc"  # shared by every track
    assert loader.major_tracks("TEST") == ["one", "two"]
    with pytest.raises(ValueError, match="no track 'three'"):
        loader.load_major("TEST", "three")


def test_major_without_tracks_loads_as_is(tmp_path):
    loader = _write_major(tmp_path, {"major_code": "TEST", "major_name": "Test",
                                     "lower_level": [{"code": "A"}]})

    major = loader.load_major("TEST")

    assert major.track == "" and [r.id for r in major.lower_level] == ["A"]
    assert loader.major_tracks("TEST") == []
    with pytest.raises(ValueError, match="no track"):
        loader.load_major("TEST", "general")


def test_prerequisites_naming_math240_also_accept_math341():
    loader = DataLoader(SAMPLE_DATA)
    condition = loader._parse_prerequisite({"type": "course", "courses": ["CMSC330", "MATH240"]})

    assert condition.is_satisfied({"CMSC330": "A", "MATH341": "A"})
    assert not condition.is_satisfied({"MATH341": "A"})
