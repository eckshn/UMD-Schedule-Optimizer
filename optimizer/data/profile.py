"""
Student profiles as JSON: who the student is, what they have credit for and
which programs they want, read into a ``StudentDegreeProgram``.

A profile is one object. Only ``majors`` is required::

    {
      "name": "Terp",
      "id": "123",
      "majors": ["CMSC", {"code": "MATH", "track": "applied"}],
      "additional_degrees": [],
      "minors": ["RAS"],
      "start": "Fall 2025",
      "completed_courses": {"CMSC131": "A", "MATH140": "B+"},
      "ap_credits": {"AP Calculus AB": "MATH140"},
      "transfer_credits": {"ENGL101": "TR"},
      "credits_completed": 31,
      "requested_courses": ["CMSC422", {"code": "PHYS161", "by_semester": 3}],
      "excluded_courses": ["CMSC411"],
      "preferred_credit_load": [15, 17],
      "include_summer": false
    }

``majors`` lists the primary major first; the others share its degree (a
double major). ``additional_degrees`` are majors earning a degree of their
own. A major is a code or ``{"code", "track"}``. ``start`` is the first
planned semester ("Fall 2025", the default, or "Spring 2026"). Every other key
is a ``StudentProfile`` field (``id`` is ``student_id``);
``credits_completed`` defaults to the catalog credits of the credited courses.
Unknown keys are errors, so typos don't go unnoticed.
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from ..models.course import Course
from ..models.requirements import MajorRequirements
from ..models.schedule import SemesterType
from ..models.student import CourseRequest, StudentDegreeProgram, StudentProfile
from .loader import DataLoader

# StudentProfile fields a profile can't set: they come from other keys
_DERIVED = {"student_id", "name", "primary_major", "declared_minors", "pending_minors"}
_PROGRAM_KEYS = {"id", "name", "majors", "additional_degrees", "minors", "start"}


class ProfileError(ValueError):
    """A profile that can't be read: bad JSON, an unknown key or program, a bad value."""


@dataclass
class Profile:
    """A student's program and where their plan starts."""
    program: StudentDegreeProgram
    start_year: int = 2025
    start_semester: SemesterType = SemesterType.FALL


def load_profile(source: Union[str, Path, Mapping[str, Any]], loader: DataLoader,
                 catalog: Optional[Mapping[str, Course]] = None) -> Profile:
    """
    Read a profile from a JSON file path or an already-parsed dict. Majors,
    tracks, minors and gen-eds come from ``loader``; ``catalog`` (if given)
    supplies the default ``credits_completed``.
    """
    data = read_profile(source)
    student_keys = {f.name for f in fields(StudentProfile)} - _DERIVED
    unknown = sorted(set(data) - student_keys - _PROGRAM_KEYS)
    if unknown:
        raise ProfileError(f"unknown profile keys: {', '.join(unknown)} "
                           f"(allowed: {', '.join(sorted(student_keys | _PROGRAM_KEYS))})")
    majors = [_major(m, loader) for m in _list(data, "majors")]
    if not majors:
        raise ProfileError("a profile needs at least one major in \"majors\"")
    degrees = [_major(m, loader) for m in _list(data, "additional_degrees")]
    minors = []
    for code in _list(data, "minors"):
        minor = loader.load_minor(str(code))
        if minor is None:
            raise ProfileError(f"unknown minor {code!r}: no minors/{code}.json in {loader.data_dir}")
        minors.append(minor)

    values: Dict[str, Any] = {k: data[k] for k in student_keys if k in data}
    if "preferred_credit_load" in values:
        load = values["preferred_credit_load"]
        if not (isinstance(load, list) and len(load) == 2 and all(isinstance(n, int) for n in load)):
            raise ProfileError("preferred_credit_load must be [min, max] credits")
        values["preferred_credit_load"] = tuple(load)
    if "requested_courses" in values:
        values["requested_courses"] = [_request(r) for r in values["requested_courses"]]
    try:
        student = StudentProfile(student_id=str(data.get("id", "")), name=str(data.get("name", "")),
                                 primary_major=majors[0].major_code, **values)
    except TypeError as error:
        raise ProfileError(str(error)) from error
    if "credits_completed" not in data and catalog is not None:
        student.credits_completed = sum(catalog[c].credits for c in sorted(student.credited_courses())
                                        if c in catalog)

    program = StudentDegreeProgram(student=student, primary_major=majors[0],
                                   additional_majors=majors[1:], minors=minors,
                                   gen_ed_requirements=loader.load_gen_eds(),
                                   additional_degrees=degrees)
    return Profile(program, *_start(data.get("start", "Fall 2025")))


def read_profile(source: Union[str, Path, Mapping[str, Any]]) -> Dict[str, Any]:
    """The profile's JSON object, unchecked (``load_profile`` checks it)."""
    if isinstance(source, Mapping):
        data = dict(source)
    else:
        try:
            data = json.loads(Path(source).read_text())
        except OSError as error:
            raise ProfileError(f"can't read {source}: {error.strerror}") from error
        except json.JSONDecodeError as error:
            raise ProfileError(f"{source} isn't valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ProfileError("a profile is a JSON object")
    return data


def _list(data: Mapping[str, Any], key: str) -> List[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ProfileError(f"{key} must be a list")
    return value


def _major(entry: Any, loader: DataLoader) -> MajorRequirements:
    if isinstance(entry, str):
        code, track = entry, None
    elif isinstance(entry, dict) and set(entry) <= {"code", "track"} and "code" in entry:
        code, track = entry["code"], entry.get("track")
    else:
        raise ProfileError(f"a major is a code or {{\"code\", \"track\"}}, not {entry!r}")
    try:
        major = loader.load_major(code, track)
    except ValueError as error:
        raise ProfileError(str(error)) from error
    if major is None:
        raise ProfileError(f"unknown major {code!r}: no majors/{code}.json in {loader.data_dir}")
    return major


def _request(entry: Any) -> CourseRequest:
    if isinstance(entry, str):
        return CourseRequest(entry)
    try:
        return CourseRequest(**entry)
    except TypeError as error:
        raise ProfileError(f"bad requested course {entry!r}: a code or "
                           "{\"code\", \"by_semester\", \"by_credits\"}") from error


def _start(text: Any) -> tuple:
    parts = str(text).split()
    if len(parts) == 2 and parts[1].isdigit():
        for semester in SemesterType:
            if semester.value.lower() == parts[0].lower():
                return int(parts[1]), semester
    raise ProfileError(f"start must look like \"Fall 2025\", not {text!r}")
