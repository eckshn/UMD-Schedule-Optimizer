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
  from the prerequisite text (the raw text is kept as ``prerequisite_text``),
  and ``corequisites`` the one it reads from the corequisite text (kept as
  ``corequisite_text``);
- ``gen_eds`` are the latest term's gen-ed option groups;
- ``credit_only_granted_for`` lists courses it shares credit with;
- permission the prerequisite text requires ("and permission of ...") is
  added to ``restrictions``.

Courses that a hand-curated file (one without ``"generated": true``) already
defines are left out, so curated data keeps priority. When the department
itself has a hand-curated file (MATH.json), the other courses go to a
supplement, ``{DEPT}_generated.json``, which loads after it; ``--force``
replaces the curated file instead.

``--offered-only`` updates just the ``offered`` lists of a hand-curated file
(CMSC.json, MATH.json) from the scrapes, looking each course up in its own
department's terms (MATH.json's STAT courses in ``stat.json``). Seasons no
scraped term covers (Summer, Winter) and courses no term lists keep their
curated values; a course without ``offered`` (which DataLoader reads as Fall
and Spring) gets one. Only ``"offered"`` lines change, so the file keeps its
hand formatting; the terms used go in ``offered_terms``.

Usage (from the repo root):
    python scrapers/generate_departments.py STAT AMSC PHYS ENEE ENME ENAE ENES
    python scrapers/generate_departments.py --offered-only CMSC MATH
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
        coreq = parse_prerequisite_text(course.get("corequisite_text", ""))
        entry = {
            "code": code,
            "name": course.get("name", code),
            "credits": credits_of(course.get("credits")),
            "description": course.get("description") or "",
            "prerequisites": [tree] if tree else [],
            "prerequisite_text": course.get("prerequisite_text", ""),
            "corequisites": [coreq] if coreq else [],
            "corequisite_text": course.get("corequisite_text", ""),
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


def department_of(code: str) -> str:
    match = re.match(r"[A-Z]+", code)
    return match.group(0) if match else code


def scraped_offerings(dept: str, terms_dir: Path) -> Tuple[List[str], Dict[str, set]]:
    """The terms scraped for ``dept`` and the seasons each course was listed in."""
    terms = sorted(p.name for p in terms_dir.iterdir()
                   if p.is_dir() and (p / f"{dept.lower()}.json").exists())
    offered: Dict[str, set] = {}
    for term in terms:
        data = json.loads((terms_dir / term / f"{dept.lower()}.json").read_text())
        for course in data.get("courses", []):
            if season(term):
                offered.setdefault(course["code"], set()).add(season(term))
    return terms, offered


_CODE_LINE = re.compile(r'^      "code": "([^"]+)"')
_OFFERED_LINE = re.compile(r'^(      "offered": )(\[[^\]]*\])(,?)$')
_AREAS_LINE = re.compile(r'^      "areas": .*,$')
_COURSE_END = re.compile(r"^    },?$")
DEFAULT_OFFERED = ["Fall", "Spring"]  # what DataLoader assumes when "offered" is missing


def update_offered(path: Path, terms_dir: Path) -> List[Tuple[str, List[str], List[str]]]:
    """
    Rewrite the ``offered`` lists of the curated file ``path`` from the scrapes
    (see the module docstring). A course without ``offered`` gets the line
    after its ``areas``. Returns ``(code, old, new)`` for each change.
    """
    scrapes: Dict[str, Tuple[List[str], Dict[str, set]]] = {}
    lines = path.read_text().splitlines(keepends=True)
    courses = []  # (code, index of its "offered" line or None, index of its "areas" line)
    code = offered_at = areas_at = None
    for i, line in enumerate(lines):
        text = line.rstrip("\n")
        if _CODE_LINE.match(text):
            code, offered_at, areas_at = _CODE_LINE.match(text).group(1), None, None
        elif code and _OFFERED_LINE.match(text):
            offered_at = i
        elif code and _AREAS_LINE.match(text):
            areas_at = i
        elif code and _COURSE_END.match(text):
            courses.append((code, offered_at, areas_at))
            code = None

    changes = []
    inserts = []
    for code, offered_at, areas_at in courses:
        dept = department_of(code)
        if dept not in scrapes:
            scrapes[dept] = scraped_offerings(dept, terms_dir)
        terms, seen = scrapes[dept]
        if code not in seen:
            continue
        old = (json.loads(_OFFERED_LINE.match(lines[offered_at].rstrip("\n")).group(2))
               if offered_at is not None else DEFAULT_OFFERED)
        new_set = (set(old) - {season(t) for t in terms}) | seen[code]
        new = [s for s in SEASON_ORDER if s in new_set]
        if offered_at is not None:
            if new_set == set(old):
                continue
            match = _OFFERED_LINE.match(lines[offered_at].rstrip("\n"))
            lines[offered_at] = f"{match.group(1)}{json.dumps(new)}{match.group(3)}\n"
        elif areas_at is not None:
            inserts.append((areas_at + 1, f'      "offered": {json.dumps(new)},\n'))
        else:
            raise SystemExit(f"{path}: {code} has neither \"offered\" nor \"areas\" to place it after")
        changes.append((code, old if offered_at is not None else [], new))
    for at, line in reversed(inserts):
        lines.insert(at, line)

    terms_used = sorted({t for terms, _ in scrapes.values() for t in terms})
    terms_line = f'  "offered_terms": {json.dumps(terms_used)},\n'
    existing = [i for i, line in enumerate(lines) if line.startswith('  "offered_terms": ')]
    if existing:
        lines[existing[0]] = terms_line
    else:
        lines.insert(lines.index('  "courses": [\n'), terms_line)
    path.write_text("".join(lines))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("departments", nargs="+", help="Department codes, e.g. STAT ENEE")
    parser.add_argument("--terms-dir", default="data/testudo_terms")
    parser.add_argument("--output", default="sample_data/courses")
    parser.add_argument("--force", action="store_true",
                        help="Replace a hand-curated department file too")
    parser.add_argument("--offered-only", action="store_true",
                        help="Only update the offered lists of hand-curated files")
    args = parser.parse_args()

    out_dir = Path(args.output)
    if args.offered_only:
        for dept in (d.upper() for d in args.departments):
            changes = update_offered(out_dir / f"{dept}.json", Path(args.terms_dir))
            print(f"{dept}: {len(changes)} offering changes")
            for code, old, new in changes:
                print(f"  {code}: {old} -> {new}")
        return
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
