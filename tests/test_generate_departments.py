"""Tests for scrapers/generate_departments.py (department files from Testudo term scrapes)."""

import importlib.util
import json
from pathlib import Path

from optimizer.data.loader import DataLoader

SCRIPT = Path(__file__).resolve().parent.parent / "scrapers" / "generate_departments.py"
spec = importlib.util.spec_from_file_location("generate_departments", SCRIPT)
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


def _term(terms_dir, term, *courses):
    path = terms_dir / term
    path.mkdir(parents=True)
    (path / "enme.json").write_text(json.dumps({"department": "ENME", "courses": list(courses)}))


def _course(code, **kwargs):
    return {"code": code, "name": kwargs.pop("name", code), "credits": 3, **kwargs}


def test_department_file_merges_terms_and_parses_prerequisites(tmp_path):
    terms = tmp_path / "terms"
    _term(terms, "202508", _course("ENME480", name="Old name",
                                   prerequisite_text="MATH246 or ENES221; and (CMSC131 or ENME202)."))
    _term(terms, "202601", _course("ENME400", credits="1-3"), _course("ENME600"),
          _course("ENME202", gen_eds=[["DSSP"]]))
    _term(terms, "202608", _course("ENME480", prerequisite_text="MATH246 or ENES221."),
          _course("ENME202"))

    data = generate.build_department("ENME", terms, exclude={"ENME202"})
    courses = {c["code"]: c for c in data["courses"]}

    assert data["generated"] and data["terms"] == ["202508", "202601", "202608"]
    assert sorted(courses) == ["ENME400", "ENME480"]  # graduate and curated courses left out
    assert courses["ENME480"]["offered"] == ["Fall"]
    assert courses["ENME480"]["prerequisites"] == [{"type": "or", "courses": ["MATH246", "ENES221"]}]
    assert courses["ENME480"]["level"] == "upper"
    assert courses["ENME400"]["credits"] == 1 and courses["ENME400"]["offered"] == ["Spring"]


def test_generated_files_load_and_curated_courses_win():
    catalog = DataLoader(Path(__file__).resolve().parent.parent / "sample_data").load_catalog()
    generated = json.loads((SCRIPT.parent.parent / "sample_data/courses/STAT.json").read_text())

    assert generated["generated"]
    assert "STAT400" not in {c["code"] for c in generated["courses"]}  # MATH.json curates it
    assert catalog["ENME480"].offered == ["Fall"]
    assert catalog["ENAE450"].prerequisites[0].courses == ["ENME480", "ENAE380"]


def test_curated_department_gets_a_supplement_file(tmp_path, monkeypatch):
    terms = tmp_path / "terms"
    path = terms / "202601"
    path.mkdir(parents=True)
    (path / "math.json").write_text(json.dumps({"department": "MATH", "courses": [
        _course("MATH140"), _course("MATH410")]}))
    courses = tmp_path / "courses"
    courses.mkdir()
    (courses / "MATH.json").write_text(json.dumps({"courses": [{"code": "MATH140", "name": "Calc", "credits": 4}]}))
    monkeypatch.setattr("sys.argv", ["generate_departments.py", "MATH", "--terms-dir", str(terms),
                                     "--output", str(courses)])

    generate.main()

    supplement = json.loads((courses / "MATH_generated.json").read_text())
    assert [c["code"] for c in supplement["courses"]] == ["MATH410"]
    assert json.loads((courses / "MATH.json").read_text())["courses"][0]["name"] == "Calc"
    assert sorted(DataLoader(tmp_path).load_catalog()) == ["MATH140", "MATH410"]


def test_required_permission_becomes_a_restriction():
    assert generate.permission_required(
        "MATH141; and permission of CMNS-Mathematics department.") == [
        "Prerequisite requires permission of CMNS-Mathematics department"]
    assert generate.permission_required("AMSC666 or CMSC666; or permission of instructor.") == []


def test_offered_only_updates_curated_offerings_in_place(tmp_path):
    terms = tmp_path / "terms"
    for term, math, stat in [("202508", ["MATH410", "MATH411"], ["STAT400"]),
                             ("202601", ["MATH410"], ["STAT400"])]:
        (terms / term).mkdir(parents=True)
        (terms / term / "math.json").write_text(json.dumps({"courses": [_course(c) for c in math]}))
        (terms / term / "stat.json").write_text(json.dumps({"courses": [_course(c) for c in stat]}))
    curated = tmp_path / "MATH.json"
    curated.write_text("""{
  "department": "MATH",
  "courses": [
    {
      "code": "MATH410",
      "areas": [],
      "offered": ["Fall", "Summer"],
      "notes": "kept"
    },
    {
      "code": "MATH411",
      "areas": ["x"],
      "notes": "no offered key"
    },
    {
      "code": "MATH412",
      "offered": ["Spring"]
    },
    {
      "code": "STAT400",
      "offered": ["Fall", "Spring", "Summer"]
    }
  ]
}
""")

    changes = generate.update_offered(curated, terms)

    # Spring added, unscraped Summer kept; a missing key is inserted after "areas";
    # an unlisted course and an unchanged one (looked up in stat.json) are left alone
    assert changes == [("MATH410", ["Fall", "Summer"], ["Fall", "Spring", "Summer"]),
                       ("MATH411", [], ["Fall"])]
    text = curated.read_text()
    assert '      "offered": ["Fall", "Spring", "Summer"],\n      "notes": "kept"' in text
    assert '      "areas": ["x"],\n      "offered": ["Fall"],\n' in text
    data = json.loads(text)
    assert data["offered_terms"] == ["202508", "202601"]
    assert [c.get("offered") for c in data["courses"]][2:] == [["Spring"], ["Fall", "Spring", "Summer"]]
    assert generate.update_offered(curated, terms) == [] and curated.read_text() == text
