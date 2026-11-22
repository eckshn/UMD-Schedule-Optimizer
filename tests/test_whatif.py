"""What-if analysis (optimizer/whatif.py) and umd-plan whatif."""

import json
from pathlib import Path

import pytest

from optimizer.cli import main
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader
from optimizer.data.profile import ProfileError, load_profile, read_profile
from optimizer.whatif import change_profile, compare, describe_changes, format_comparison

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "examples" / "profiles"
BASE = {"majors": ["CMSC", {"code": "MATH", "track": "applied"}],
        "additional_degrees": ["PHYS"], "minors": ["RAS"], "name": "T"}


def test_switch_add_and_drop_programs():
    changed = change_profile(BASE, switch_major="STAT:x", add_major=["AMSC"],
                             add_degree=["ENEE"], drop_major=["MATH"], add_minor=["CS"],
                             drop_minor=["RAS"])

    assert changed["majors"] == [{"code": "STAT", "track": "x"}, "AMSC"]
    assert changed["additional_degrees"] == ["PHYS", "ENEE"]
    assert changed["minors"] == ["CS"]
    assert changed["name"] == "T"
    assert BASE["majors"][0] == "CMSC" and BASE["minors"] == ["RAS"]  # the input is untouched


def test_dropping_the_primary_major_promotes_the_next():
    assert change_profile(BASE, drop_major=["CMSC"])["majors"] == [{"code": "MATH", "track": "applied"}]
    only = change_profile({"majors": ["CMSC"], "additional_degrees": ["MATH"]}, drop_major=["CMSC"])
    assert only["majors"] == ["MATH"] and only["additional_degrees"] == []


@pytest.mark.parametrize("changes, message", [
    ({"drop_major": ["XYZ"]}, "no major XYZ"),
    ({"drop_minor": ["XYZ"]}, "no minor XYZ"),
    ({"drop_major": ["CMSC"]}, "leaves nothing"),
])
def test_impossible_changes_are_errors(changes, message):
    with pytest.raises(ProfileError, match=message):
        change_profile({"majors": ["CMSC"]}, **changes)


def test_describe_changes():
    assert describe_changes(switch_major="MATH", add_minor=["RAS"]) == "switch major to MATH; add minor RAS"
    assert describe_changes() == "no change"


@pytest.fixture(scope="module")
def setup():
    loader = DataLoader(ROOT / "sample_data")
    catalog = loader.load_catalog()
    return loader, catalog, ScheduleOptimizer(catalog, use_solver=False)


def test_switching_majors_shows_credited_courses_that_stop_counting(setup):
    loader, catalog, optimizer = setup
    data = read_profile(PROFILES / "cs_junior_ras.json")
    before = load_profile(data, loader, catalog)
    after = load_profile(change_profile(data, switch_major="MATH", drop_minor=["RAS"]), loader, catalog)

    comparison = compare(optimizer, before, after)

    assert "CMSC330" in comparison.before.credited_counting
    assert "CMSC330" not in comparison.after.credited_counting
    assert set(comparison.added).isdisjoint(comparison.dropped)
    assert "ENME480" in comparison.dropped
    text = format_comparison(comparison, "switch major to MATH")
    assert text.startswith("What if: switch major to MATH\n")
    assert "Credited courses that would no longer count:" in text and "CMSC330" in text
    assert "Programs" in text and "MATH (traditional)" in text


def run(capsys, *argv):
    status = main([*argv, "--data-dir", str(ROOT / "sample_data")])
    return status, capsys.readouterr()


def test_whatif_adds_a_minor(capsys):
    status, out = run(capsys, "whatif", str(PROFILES / "cs_freshman.json"), "--add-minor", "RAS",
                      "--no-solver", "--json")

    data = json.loads(out.out)
    assert status == 0
    assert data["change"] == "add minor RAS"
    assert data["now"]["programs"]["minors"] == [] and data["what_if"]["programs"]["minors"] == ["RAS"]
    assert data["what_if"]["requirements"] > data["now"]["requirements"]
    assert "ENME480" in data["added"]


def test_whatif_needs_a_change(capsys):
    status, out = run(capsys, "whatif", str(PROFILES / "cs_freshman.json"))

    assert status == 2 and "needs a change" in out.err


def test_whatif_reports_bad_changes(capsys):
    status, out = run(capsys, "whatif", str(PROFILES / "cs_freshman.json"), "--add-minor", "NOPE")

    assert status == 2 and "unknown minor 'NOPE'" in out.err
