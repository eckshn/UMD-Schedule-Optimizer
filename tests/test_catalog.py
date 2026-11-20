"""Tests for the Catalog mapping and catalog assembly."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType


@pytest.fixture
def catalog():
    return Catalog({
        code: Course(code=code, name=name, credits=3, level=level, areas=areas)
        for code, name, level, areas in [
            ("AAAS100", "Intro", "lower", []),
            ("AAAS100H", "Intro (Honors)", "lower", []),
            ("CHEM298Q", "Quantum Steampunk", "lower", []),
            ("ARHU270", "Quantum Steampunk", "lower", []),
            ("CMSC330", "Languages", "upper", ["Area1", "Area2"]),
            ("CMSC498A", "Special Topics", "upper", []),
            ("CMSC631", "Grad", "upper", []),
        ]
    })


def test_catalog_is_a_read_only_mapping(catalog):
    assert isinstance(catalog, Mapping)
    assert len(catalog) == 7
    assert "CMSC330" in catalog and "MISSING" not in catalog
    assert catalog.get("MISSING") is None
    assert list(catalog)[:2] == ["AAAS100", "AAAS100H"]
    assert {**catalog}["ARHU270"].name == "Quantum Steampunk"
    with pytest.raises(TypeError):
        catalog["NEW100"] = catalog["CMSC330"]


def test_catalog_of_wraps_dicts_once(catalog):
    assert Catalog.of(catalog) is catalog
    assert isinstance(Catalog.of({}), Catalog)
    assert isinstance(ScheduleOptimizer({}).course_catalog, Catalog)


def test_equivalents(catalog):
    assert catalog.equivalents("AAAS100") == {"AAAS100", "AAAS100H"}
    assert catalog.equivalents("AAAS100H") == {"AAAS100", "AAAS100H"}
    assert catalog.equivalents("CHEM298Q") == {"CHEM298Q", "CHEM298QH", "ARHU270"}
    assert catalog.equivalents("NOPE101") == {"NOPE101", "NOPE101H"}
    assert catalog.has_equivalent_in("ARHU270", {"CHEM298Q"})
    assert catalog.has_equivalent_in("AAAS100", ["AAAS100H"])
    assert not catalog.has_equivalent_in("CMSC330", {"AAAS100"})


def test_dedupe_equivalents_keeps_order_and_prefers_base(catalog):
    codes = ["CMSC330", "AAAS100H", "ARHU270", "AAAS100", "CHEM298Q", "CMSC330"]
    assert catalog.dedupe_equivalents(codes) == ["CMSC330", "ARHU270", "AAAS100"]


def test_course_number():
    assert Catalog.course_number("CMSC131") == 131
    assert Catalog.course_number("CMSC498A") == 498
    assert Catalog.course_number("garbage") is None


def test_primary_area(catalog):
    assert catalog.primary_area("CMSC330") == "Area1"
    assert catalog.primary_area("AAAS100") is None
    assert catalog.primary_area("MISSING") is None


def _write_courses(directory: Path, dept: str, courses):
    (directory / f"{dept}.json").write_text(json.dumps({"courses": courses}))


def test_department_files_override_gened_but_keep_its_gen_eds(tmp_path):
    courses_dir = tmp_path / "courses"
    courses_dir.mkdir()
    _write_courses(courses_dir, "GENED", [
        {"code": "MATH140", "name": "Calculus I", "credits": 4, "gen_eds": [["FSAR", "FSMA"]]},
        {"code": "MATH115", "name": "Precalculus", "credits": 3, "gen_eds": [["FSMA"]]},
        {"code": "ENGL101", "name": "Writing", "credits": 3, "gen_eds": [["FSAW"]]},
    ])
    _write_courses(courses_dir, "MATH", [
        {"code": "MATH140", "name": "Calculus I", "credits": 4, "difficulty": 3.5,
         "gen_ed_categories": ["MA"]},
        {"code": "MATH115", "name": "Precalculus", "credits": 3, "gen_eds": [["DSNS"]]},
    ])

    catalog = DataLoader(tmp_path).load_catalog()

    assert isinstance(catalog, Catalog)
    assert list(catalog) == ["MATH140", "MATH115", "ENGL101"]
    math140 = catalog["MATH140"]
    assert math140.difficulty == 3.5  # department entry wins
    assert math140.gen_ed_options == [["FSAR", "FSMA"]]
    assert math140.gen_ed_categories == ["FSAR", "FSMA"]
    assert catalog["MATH115"].gen_ed_options == [["DSNS"]]  # real options are kept


def test_sample_catalog_math140_counts_as_fsma():
    catalog = DataLoader(Path("sample_data")).load_catalog()
    assert catalog["MATH140"].get_gen_ed_option_for_category("FSMA") == ["FSAR", "FSMA"]
    assert catalog["CMSC131"].code == "CMSC131"


def _needs(type, *codes):
    return [PrerequisiteCondition(type=PrerequisiteType(type), courses=list(codes))]


def test_requires_follows_prerequisite_chains_and_needs_every_alternative():
    catalog = Catalog({
        code: Course(code=code, name=code, credits=3, prerequisites=prereqs)
        for code, prereqs in [
            ("MATH140", []),
            ("MATH141", _needs("course", "MATH140")),
            ("MATH240", _needs("course", "MATH141")),
            ("MATH461", _needs("course", "MATH141")),
            ("MATH410", _needs("or", "MATH240", "MATH461")),       # both alternatives need MATH141
            ("STAT420", _needs("or", "SURV410", "MATH410")),       # SURV410 isn't in the catalog
            ("MATH115", []),
            ("MATH220", _needs("or", "MATH115", "MATH141")),       # MATH115 avoids MATH141
            ("LOOP1", _needs("course", "LOOP2")),
            ("LOOP2", _needs("course", "LOOP1")),
        ]
    })

    assert catalog.requires("MATH240", "MATH141")
    assert catalog.requires("MATH410", "MATH141")
    assert catalog.requires("STAT420", "MATH141")
    assert catalog.requires("MATH240", "MATH140")
    assert catalog.requires("MATH240", "MATH141H")  # honors equivalent
    assert not catalog.requires("MATH141", "MATH141")
    assert not catalog.requires("MATH220", "MATH141")
    assert not catalog.requires("LOOP1", "MATH141")
    assert not catalog.requires("NOPE100", "MATH141")


def test_cross_listed_courses_share_areas_and_category_filters():
    from optimizer.core.categories import category_matches
    from optimizer.models.requirements import Requirement, RequirementType
    catalog = Catalog({
        "CMSC460": Course(code="CMSC460", name="Computational Methods", credits=3, areas=["Area5"]),
        "AMSC460": Course(code="AMSC460", name="Computational Methods", credits=3),
    })
    math_amsc = Requirement(id="m", name="m", type=RequirementType.CATEGORY, min_courses=1,
                            pattern="(MATH|AMSC|STAT)4")

    assert catalog.primary_area("AMSC460") == "Area5"
    assert category_matches(math_amsc, "CMSC460", catalog)
    assert not category_matches(math_amsc, "CMSC460", catalog, equivalents=False)


def test_credit_conflicts_pair_a_course_with_its_own_list_only():
    catalog = Catalog({
        "MATH341": Course(code="MATH341", name="Honors", credits=4,
                          credit_only_one_of=["MATH240", "MATH246", "MATH341"]),
        "MATH240": Course(code="MATH240", name="Linear Algebra", credits=4),
        "MATH246": Course(code="MATH246", name="ODE", credits=3),
    })

    assert catalog.credit_conflicts("MATH341") == {"MATH240", "MATH246"}
    assert catalog.credit_conflicts("MATH240") == {"MATH341"}  # 240 and 246 don't overlap
    assert catalog.has_credit_conflict_in("MATH246", ["MATH341"])
