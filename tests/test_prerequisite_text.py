"""Tests for reading UMD prerequisite sentences (optimizer/data/prerequisite_text.py)."""

import pytest

from optimizer.data.prerequisite_text import parse_prerequisite_text


def course(code):
    return {"type": "course", "courses": [code]}


def any_of(*codes, conditions=None):
    node = {"type": "or", "courses": list(codes)}
    if conditions:
        node["conditions"] = conditions
    return node


def all_of(*conditions):
    return {"type": "and", "conditions": list(conditions)}


@pytest.mark.parametrize("text, expected", [
    ("ENME331.", course("ENME331")),
    ("ENME351 and ENME361.", all_of(course("ENME351"), course("ENME361"))),
    ("PHYS271, ENME350, and PHYS270.", all_of(course("PHYS271"), course("ENME350"), course("PHYS270"))),
    ("BMGT190, ENES190, ENED290 or BMGT290.", any_of("BMGT190", "ENES190", "ENED290", "BMGT290")),
    # ENME480: "; and" joins clauses, commas follow "or"
    ("MATH246 or ENES221; and (CMSC131, ENME202, ENAE202 or ENEE150).",
     all_of(any_of("MATH246", "ENES221"), any_of("CMSC131", "ENME202", "ENAE202", "ENEE150"))),
    # "; or" alternatives, and alternatives naming no course are dropped
    ("Minimum grade of C- in ENEE140; or minimum grade of C- in CMSC131; and permission of "
     "ENGR- Electrical & Computer Engineering department.", any_of("ENEE140", "CMSC131")),
    ("Permission of ENGR-Electrical & Computer Engineering department. Minimum grade of C- in "
     "ENEE140 or CMSC131; or a score of 5 on the Computer Science A AP exam.",
     any_of("ENEE140", "CMSC131")),
    ("PHYS273 and MATH243, or equivalent, or permission of instructor.",
     all_of(course("PHYS273"), course("MATH243"))),
    # "1 course ... from (...)" and "one of the following" are ORs
    ("1 course with a minimum grade of C- from (CMSC106, CMSC131); and minimum grade of C- in MATH410.",
     all_of(any_of("CMSC106", "CMSC131"), course("MATH410"))),
    ("Minimum grade of C- in one of the following courses: ENEE491, ENMA434, PHYS360, or PHYS401.",
     any_of("ENEE491", "ENMA434", "PHYS360", "PHYS401")),
    # "and" binds more loosely than "or"; parentheses group
    ("CHEM131; and (MATH136 or MATH140); and BSCI160, BSCI170, and either BSCI180 or "
     "(BSCI161 and BSCI171).",
     all_of(course("CHEM131"), any_of("MATH136", "MATH140"), course("BSCI160"), course("BSCI170"),
            any_of("BSCI180", conditions=[all_of(course("BSCI161"), course("BSCI171"))]))),
    # "or" inside "C- or higher" isn't an alternative
    ("A grade of C- or higher in ENME202 and ENME331.", all_of(course("ENME202"), course("ENME331"))),
    ("Must have completed or be concurrently enrolled in ENME361.", course("ENME361")),
    ("Permission of department.", None),
    ("", None),
])
def test_parse_prerequisite_text(text, expected):
    assert parse_prerequisite_text(text) == expected
