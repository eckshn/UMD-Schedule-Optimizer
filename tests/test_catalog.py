"""Tests for the Catalog mapping and catalog assembly."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.models.catalog import Catalog
from optimizer.models.course import Course


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
