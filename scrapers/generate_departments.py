#!/usr/bin/env python3
"""
Build department course files (``sample_data/courses/{DEPT}.json``) from
Testudo scrapes of several terms (``data/testudo_terms/{term}/{dept}.json``,
written by ``scrape_testudo.py --term {term} --output data/testudo_terms/{term}``).

For each undergraduate course (numbered up to 499) seen in any term:

- name, credits, description, prerequisite text and restrictions come from the
  latest term listing it;
- ``offered`` is every season (Fall/Spring/...) it was listed in;
- ``prerequisites`` is the tree ``optimizer.data.prerequisite_text`` reads
  from the prerequisite text (the raw text is kept as ``prerequisite_text``);
- ``gen_eds`` are the latest term's gen-ed option groups;
- ``credit_only_granted_for`` lists courses it shares credit with;
- permission the prerequisite text requires ("and permission of ...") is
  added to ``restrictions``.

Courses that a hand-curated file (one without ``"generated": true``) already
defines are left out, so curated data keeps priority. When the department
itself has a hand-curated file (MATH.json), the other courses go to a
supplement, ``{DEPT}_generated.json``, which loads after it; ``--force``
replaces the curated file instead.

Usage (from the repo root):
    python scrapers/generate_departments.py STAT AMSC PHYS ENEE ENME ENAE ENES
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from optimizer.data.prerequisite_text import parse_prerequisite_text  # noqa: E402

SEASONS = {"01": "Spring", "05": "Summer", "08": "Fall", "12": "Winter"}
SEASON_ORDER = ["Fall", "Spring", "Summer", "Winter"]


def season(term: str) -> Optional[str]:
    """``202608`` -> ``Fall``."""
    return SEASONS.get(term[-2:])


def course_number(code: str) -> Optional[int]:
    match = re.match(r"[A-Z]+(\d+)", code)
    return int(match.group(1)) if match else None


def credits_of(value) -> int:
    """Testudo credits: an int, or a range such as "1-3" (its minimum)."""
    if isinstance(value, int):
        return value
    match = re.match(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


_REQUIRED_PERMISSION = re.compile(r"(?:^|[;.]|\band)\s*(permission[^;.]*)", re.IGNORECASE)


def permission_required(prerequisite_text: str) -> List[str]:
    """
    Permission a prerequisite requires ("...; and permission of CMNS-Mathematics
    department"), as restrictions. Permission offered as an alternative ("or
    permission of instructor") isn't a restriction.
    """
    return [f"Prerequisite requires {m.group(1).strip()}"
            for m in _REQUIRED_PERMISSION.finditer(prerequisite_text or "")]


def curated_codes(courses_dir: Path, skip: Path) -> set:
    """Codes defined by hand-curated department files (not GENED, not generated, not ``skip``)."""
    codes = set()
    for path in sorted(courses_dir.glob("*.json")):
        if path.name == "GENED.json" or path == skip:
            continue
        data = json.loads(path.read_text())
        if not data.get("generated"):
            codes.update(c["code"] for c in data.get("courses", []))
    return codes


def build_department(dept: str, terms_dir: Path, exclude: set) -> Dict:
    terms = sorted(p.name for p in terms_dir.iterdir()
                   if p.is_dir() and (p / f"{dept.lower()}.json").exists())
    if not terms:
        raise SystemExit(f"No scraped terms for {dept} under {terms_dir}")
    latest: Dict[str, Dict] = {}
    offered: Dict[str, set] = {}
    for term in terms:  # in order, so later terms overwrite earlier ones
        data = json.loads((terms_dir / term / f"{dept.lower()}.json").read_text())
        for course in data.get("courses", []):
            code = course["code"]
            number = course_number(code)
            if number is None or number > 499 or code in exclude:
                continue
            latest[code] = course
            if season(term):
                offered.setdefault(code, set()).add(season(term))

    courses: List[Dict] = []
    for code in sorted(latest):
        course = latest[code]
        tree = parse_prerequisite_text(course.get("prerequisite_text", ""))
        entry = {
            "code": code,
            "name": course.get("name", code),
            "credits": credits_of(course.get("credits")),
            "description": course.get("description") or "",
            "prerequisites": [tree] if tree else [],
            "prerequisite_text": course.get("prerequisite_text", ""),
            "corequisites": course.get("corequisites", []),
            "level": "upper" if course_number(code) >= 300 else "lower",
            "offered": [s for s in SEASON_ORDER if s in offered.get(code, ())],
            "restrictions": course.get("restrictions", []) + permission_required(
                course.get("prerequisite_text", "")),
        }
        if course.get("credit_only_granted_for"):
            entry["credit_only_granted_for"] = course["credit_only_granted_for"]
        if course.get("gen_eds"):
            entry["gen_eds"] = course["gen_eds"]
        courses.append(entry)
    return {
        "department": dept,
        "generated": True,
        "source": "Testudo Schedule of Classes (scrapers/generate_departments.py)",
        "terms": terms,
        "courses": courses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("departments", nargs="+", help="Department codes, e.g. STAT ENEE")
    parser.add_argument("--terms-dir", default="data/testudo_terms")
    parser.add_argument("--output", default="sample_data/courses")
    parser.add_argument("--force", action="store_true",
                        help="Replace a hand-curated department file too")
    args = parser.parse_args()

    out_dir = Path(args.output)
    for dept in (d.upper() for d in args.departments):
        target = out_dir / f"{dept}.json"
        if target.exists() and not json.loads(target.read_text()).get("generated") and not args.force:
            target = out_dir / f"{dept}_generated.json"  # supplement the curated file
        data = build_department(dept, Path(args.terms_dir), curated_codes(out_dir, skip=target))
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        parsed = sum(1 for c in data["courses"] if c["prerequisites"])
        print(f"{dept}: {len(data['courses'])} courses from terms {', '.join(data['terms'])} "
              f"({parsed} with prerequisites) -> {target}")


if __name__ == "__main__":
    main()
