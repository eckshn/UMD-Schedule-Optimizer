"""Data loading utilities."""

import json
import logging
from dataclasses import fields
from pathlib import Path
from typing import Dict, List, Optional
from ..core import rules
from ..models.catalog import Catalog
from ..models.course import Course, PrerequisiteCondition, PrerequisiteType
from ..models.requirements import (
    Requirement, RequirementType, MajorRequirements, 
    MinorRequirements, EligibilityRequirement
)

logger = logging.getLogger(__name__)


class DataLoader:
    """Loads course and requirement data from JSON files."""
    
    def __init__(self, data_dir: Path):
        """
        Initialize the data loader.
        
        Args:
            data_dir: Path to the directory containing data files
        """
        self.data_dir = Path(data_dir)
    
    def load_courses(self, department: str) -> Dict[str, Course]:
        """
        Load courses for a department from JSON file.
        
        Args:
            department: Department code (e.g., "CMSC")
            
        Returns:
            Dictionary mapping course codes to Course objects
        """
        filepath = self.data_dir / "courses" / f"{department}.json"
        
        if not filepath.exists():
            logger.warning("Course file not found: %s", filepath)
            return {}
        return self._read_courses(filepath)

    def load_catalog(self) -> Catalog:
        """
        Build the catalog from every ``courses/*.json`` file.

        GENED.json aggregates the Gen Ed courses of every department, so it is
        loaded first and the curated department files (in name order) override
        its entries. A department entry without Gen Ed options keeps the ones
        GENED.json lists for that course.
        """
        courses_dir = self.data_dir / "courses"
        if not courses_dir.exists():
            logger.warning("Courses directory not found: %s", courses_dir)
            return Catalog()

        courses: Dict[str, Course] = {}
        files = sorted(courses_dir.glob("*.json"), key=lambda p: (p.stem != "GENED", p.name))
        for filepath in files:
            for code, course in self._read_courses(filepath).items():
                previous = courses.get(code)
                if previous and previous.gen_ed_options and not course.gen_ed_options:
                    course.gen_ed_options = previous.gen_ed_options
                    course.gen_ed_categories = previous.gen_ed_categories
                courses[code] = course
        return Catalog(courses)

    def load_all_courses(self) -> Catalog:
        """Alias of ``load_catalog``."""
        return self.load_catalog()

    def _read_courses(self, filepath: Path) -> Dict[str, Course]:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return {course.code: course
                for course in map(self._parse_course, data.get("courses", []))}
    
    def _parse_course(self, data: Dict) -> Course:
        """Parse course data from JSON."""
        prereqs = []
        for prereq_data in data.get("prerequisites", []):
            prereq = self._parse_prerequisite(prereq_data)
            if prereq:
                prereqs.append(prereq)
        
        # Handle gen_eds field (from Testudo scraper) as well as gen_ed_categories
        # New format: gen_eds is a list of lists, e.g., [['DSHS'], ['DSHU', 'DVUP', 'SCIS']]
        # This means: EITHER option 1 OR option 2
        gen_ed_cats = data.get("gen_ed_categories", [])
        gen_ed_opts = []
        
        if "gen_eds" in data:
            gen_ed_opts = data["gen_eds"]
            
            # For backwards compatibility, also flatten into gen_ed_categories
            # but the optimizer should use gen_ed_options instead
            if not gen_ed_cats:
                gen_ed_cats = []
                for option in data["gen_eds"]:
                    if isinstance(option, list):
                        gen_ed_cats.extend(option)
                    else:
                        # Handle legacy format where it might be a simple string
                        gen_ed_cats.append(option)
        
        return Course(
            code=data["code"],
            name=data["name"],
            credits=data.get("credits", 3),
            description=data.get("description", ""),
            prerequisites=prereqs,
            corequisites=data.get("corequisites", []),
            level=data.get("level", "lower"),
            areas=data.get("areas", []),
            offered=data.get("offered", data.get("semesters_offered", ["Fall", "Spring"])),
            typical_sections=data.get("typical_sections", 1),
            difficulty=data.get("difficulty", 3.0),
            workload_hours=data.get("workload_hours", 10.0),
            gen_ed_categories=gen_ed_cats,
            gen_ed_options=gen_ed_opts,
            restrictions=data.get("restrictions", []),
            credit_only_one_of=data.get("credit_only_granted_for", []),
            notes=data.get("notes", "")
        )
    
    def _parse_prerequisite_overrides(self, data: Dict) -> Dict[str, List[PrerequisiteCondition]]:
        """
        A program's ``prerequisite_overrides``: course code -> a list of
        prerequisites in the course-file format, which replace the catalog's
        for the program's students.
        """
        return {code: [c for c in map(self._parse_prerequisite, items) if c]
                for code, items in data.get("prerequisite_overrides", {}).items()}

    def _parse_prerequisite(self, data) -> Optional[PrerequisiteCondition]:
        """
        Parse a prerequisite condition from JSON, letting the courses in
        ``rules.PREREQUISITE_SUBSTITUTES`` stand in where they apply (a
        prerequisite of MATH240 also accepts MATH341).
        """
        condition = self._parse_prerequisite_tree(data)
        return _with_substitutes(condition) if condition else None

    def _parse_prerequisite_tree(self, data) -> Optional[PrerequisiteCondition]:
        # Handle simple string format (just a course code)
        if isinstance(data, str):
            return PrerequisiteCondition(
                type=PrerequisiteType.COURSE,
                courses=[data],
                min_grade=None
            )
        
        if not isinstance(data, dict):
            return None
            
        prereq_type_str = data.get("type", "course")
        
        if prereq_type_str == "course":
            prereq_type = PrerequisiteType.COURSE
            return PrerequisiteCondition(
                type=prereq_type,
                courses=data.get("courses", []),
                min_grade=data.get("min_grade")
            )
        
        elif prereq_type_str == "or":
            conditions = [c for c in map(self._parse_prerequisite_tree, data.get("conditions", [])) if c]
            return PrerequisiteCondition(
                type=PrerequisiteType.OR,
                courses=data.get("courses", []),
                conditions=conditions or None,
            )
        
        elif prereq_type_str == "and":
            prereq_type = PrerequisiteType.AND
            conditions = []
            for cond_data in data.get("conditions", []):
                cond = self._parse_prerequisite_tree(cond_data)
                if cond:
                    conditions.append(cond)
            return PrerequisiteCondition(
                type=prereq_type,
                conditions=conditions
            )
        
        return None
    
    def major_tracks(self, major_code: str) -> List[str]:
        """The tracks (specializations) ``majors/{major_code}.json`` defines, default first."""
        data = self._read_json("majors", major_code) or {}
        tracks = list(data.get("tracks", {}))
        default = data.get("default_track")
        return ([default] if default in tracks else []) + [t for t in tracks if t != default]

    def load_major(self, major_code: str, track: Optional[str] = None) -> Optional[MajorRequirements]:
        """
        Load major requirements from ``majors/{major_code}.json``.

        A major with ``tracks`` (specializations) holds the requirements every
        track shares at the top level, and each track's own under
        ``tracks.{name}``; ``track`` picks one (default: ``default_track``).
        A track's requirement replaces a shared one with the same ``id`` (or
        ``code``) in place; others are appended to that section. Other track
        keys (``major_name``, ``concentration``, ...) replace the shared value.

        Each of ``lower_level``, ``upper_level`` and ``supporting_courses`` is a
        list of requirement objects (see ``_parse_requirement``). ``benchmarks``
        maps a credit count (a string key, e.g. ``"45"``) to such a list.
        """
        data = self._read_json("majors", major_code)
        if data is None:
            return None
        tracks = data.get("tracks", {})
        track = track or data.get("default_track")
        if track is not None or tracks:
            if track not in tracks:
                raise ValueError(f"{major_code} has no track {track!r} "
                                 f"(tracks: {', '.join(tracks) or 'none'})")
            data = _apply_track(data, tracks[track])

        concentration = data.get("concentration")

        return MajorRequirements(
            major_code=data["major_code"],
            major_name=data["major_name"],
            track=track or "",
            department=data.get("department", ""),
            degree_type=data.get("degree_type", "BS"),
            lower_level=self._parse_requirement_list(data.get("lower_level", [])),
            upper_level=self._parse_requirement_list(data.get("upper_level", [])),
            supporting_courses=self._parse_requirement_list(data.get("supporting_courses", [])),
            concentration=self._parse_requirement(concentration) if concentration else None,
            benchmarks={int(credits): self._parse_requirement_list(items)
                        for credits, items in data.get("benchmarks", {}).items()} or None,
            prerequisite_overrides=self._parse_prerequisite_overrides(data),
            min_credits=data.get("min_credits", 120),
            min_major_credits=data.get("min_major_credits", 0),
            min_upper_level_credits=data.get("min_upper_level_credits", 0),
            min_gpa=data.get("min_gpa", 2.0),
            min_major_gpa=data.get("min_major_gpa", 2.0),
        )

    def load_minor(self, minor_code: str) -> Optional[MinorRequirements]:
        """
        Load minor requirements from ``minors/{minor_code}.json``.

        ``core_courses``, ``supporting_courses`` and ``electives`` are lists of
        requirement objects; ``eligibility`` maps onto ``EligibilityRequirement``.
        """
        data = self._read_json("minors", minor_code)
        if data is None:
            return None

        eligibility_data = data.get("eligibility", {})
        eligibility = EligibilityRequirement(**{
            f.name: eligibility_data[f.name]
            for f in fields(EligibilityRequirement)
            if f.name in eligibility_data
        })

        return MinorRequirements(
            minor_code=data["minor_code"],
            minor_name=data["minor_name"],
            department=data.get("department", ""),
            eligibility=eligibility,
            core_courses=self._parse_requirement_list(data.get("core_courses", [])),
            supporting_courses=self._parse_requirement_list(data.get("supporting_courses", [])),
            electives=self._parse_requirement_list(data.get("electives", [])),
            min_credits=data.get("min_credits", 18),
            min_gpa=data.get("min_gpa", 2.0),
            min_grade=data.get("min_grade", "C-"),
            must_complete_with_major=data.get("must_complete_with_major", True),
            max_overlap_with_major=data.get("max_overlap_with_major"),
            course_sequence=data.get("course_sequence"),
            fixed_schedule=data.get("fixed_schedule", False),
            prerequisite_overrides=self._parse_prerequisite_overrides(data),
            restricted_enrollment=data.get("restricted_enrollment", False),
            requires_permission_per_course=data.get("requires_permission_per_course", False),
        )

    def load_gen_eds(self, institution: str = "UMD") -> List[Requirement]:
        """
        Load university-wide gen-ed requirements from ``gen_eds/{institution}.json``,
        shaped as ``{"requirements": [...]}`` (see ``_parse_requirement``).
        Returns an empty list if the file is missing.
        """
        data = self._read_json("gen_eds", institution)
        if data is None:
            return []
        return self._parse_requirement_list(data["requirements"])

    def _read_json(self, subdir: str, code: str) -> Optional[Dict]:
        """Read ``data_dir/subdir/{code}.json``, or warn and return None."""
        filepath = self.data_dir / subdir / f"{code}.json"
        if not filepath.exists():
            logger.warning("File not found: %s", filepath)
            return None
        with open(filepath, 'r') as f:
            return json.load(f)

    def _parse_requirement_list(self, items: List) -> List[Requirement]:
        return [self._parse_requirement(item) for item in items]

    def _parse_requirement(self, data: Dict) -> Requirement:
        """
        Parse a requirement object. Keys match the fields of ``Requirement``;
        ``type`` is a ``RequirementType`` value such as "group" or "gen_ed".

        Shorthand: ``{"code": "CMSC131", "name": ...}`` with no ``type`` is a
        single-course requirement. Entries in ``courses``/``choices`` may be
        course-code strings or nested requirement objects.
        """
        if "type" not in data and "code" in data:
            data = {
                "id": data["code"],
                "name": data.get("name", data["code"]),
                "type": "course",
                "course_code": data["code"],
                **{k: v for k, v in data.items() if k not in ("code", "name")},
            }

        kwargs = {
            f.name: data[f.name]
            for f in fields(Requirement)
            if f.name in data and f.name != "type"
        }
        kwargs["type"] = RequirementType(data.get("type", "group"))
        kwargs.setdefault("id", kwargs.get("name", "requirement"))
        kwargs.setdefault("name", kwargs["id"])

        for key in ("courses", "choices"):
            if kwargs.get(key) is not None:
                kwargs[key] = [
                    item if isinstance(item, str) else self._parse_requirement(item)
                    for item in kwargs[key]
                ]

        return Requirement(**kwargs)


_TRACK_SECTIONS = ("lower_level", "upper_level", "supporting_courses")


def _apply_track(major: Dict, track: Dict) -> Dict:
    """
    The major's data with ``track`` applied: in each requirement section, a
    track requirement replaces the shared one with the same id (or ``code``),
    others are appended; any other track key replaces the shared value.
    """
    merged = {k: v for k, v in major.items() if k not in ("tracks", "default_track")}
    for key, value in track.items():
        if key not in _TRACK_SECTIONS:
            merged[key] = value
    for section in _TRACK_SECTIONS:
        items = list(major.get(section, []))
        position = {_requirement_id(item): i for i, item in enumerate(items)}
        for item in track.get(section, []):
            if _requirement_id(item) in position:
                items[position[_requirement_id(item)]] = item
            else:
                items.append(item)
        merged[section] = items
    return merged


def _requirement_id(item: Dict) -> Optional[str]:
    return item.get("id") or item.get("code")


def _with_substitutes(condition: PrerequisiteCondition) -> PrerequisiteCondition:
    """``condition`` with ``rules.PREREQUISITE_SUBSTITUTES`` added as alternatives."""
    subs = rules.PREREQUISITE_SUBSTITUTES
    nested = [_with_substitutes(c) for c in condition.conditions or []] or None
    if condition.type == PrerequisiteType.OR:
        courses = list(condition.courses or [])
        courses += [s for c in courses for s in subs.get(c, ()) if s not in courses]
        return PrerequisiteCondition(PrerequisiteType.OR, courses=courses, conditions=nested)
    if condition.type == PrerequisiteType.AND:
        return PrerequisiteCondition(PrerequisiteType.AND, conditions=nested)
    courses = condition.courses or []
    if not any(c in subs for c in courses):
        return condition
    parts = [PrerequisiteCondition(PrerequisiteType.OR, courses=[c, *subs[c]]) if c in subs
             else PrerequisiteCondition(PrerequisiteType.COURSE, courses=[c], min_grade=condition.min_grade)
             for c in courses]
    return parts[0] if len(parts) == 1 else PrerequisiteCondition(PrerequisiteType.AND, conditions=parts)
