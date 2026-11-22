"""
What-if analysis: plan the student's program as it is and with a change
(switching majors, adding or dropping a major, degree or minor) and compare.

``change_profile`` edits a profile dict (``optimizer.data.profile`` format);
``compare`` plans and audits both versions; ``format_comparison`` shows when
each graduates, how many terms and credits it takes, how many requirements
it meets, how many credited courses still count toward a major or minor, and
which courses the change adds or drops.
"""

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .core.audit import AuditReport
from .core.optimizer import ScheduleOptimizer
from .data.profile import Profile, ProfileError
from .models.schedule import Schedule

def change_profile(data: Mapping[str, Any], switch_major: Optional[str] = None,
                   add_major: Sequence[str] = (), add_degree: Sequence[str] = (),
                   drop_major: Sequence[str] = (), add_minor: Sequence[str] = (),
                   drop_minor: Sequence[str] = ()) -> Dict[str, Any]:
    """
    A copy of profile ``data`` with the changes made. Majors are written
    ``CODE`` or ``CODE:TRACK``. ``switch_major`` replaces the primary major;
    ``add_major`` adds a major to the same degree, ``add_degree`` one with a
    degree of its own; ``drop_major`` removes a major from either (the next
    one becomes primary). Raises ``ProfileError`` for a program to drop that
    the profile doesn't have, or when no major would be left.
    """
    changed = copy.deepcopy(dict(data))
    majors = list(changed.get("majors", []))
    degrees = list(changed.get("additional_degrees", []))
    minors = list(changed.get("minors", []))
    if switch_major:
        if not majors:
            raise ProfileError("the profile has no major to switch")
        majors[0] = _major(switch_major)
    majors += [_major(m) for m in add_major]
    degrees += [_major(m) for m in add_degree]
    for code in drop_major:
        code = code.split(":")[0]
        kept = [m for m in majors if _code(m) != code]
        kept_degrees = [m for m in degrees if _code(m) != code]
        if len(kept) == len(majors) and len(kept_degrees) == len(degrees):
            raise ProfileError(f"no major {code} to drop")
        majors, degrees = kept, kept_degrees
    if not majors:
        if not degrees:
            raise ProfileError("dropping every major leaves nothing to plan")
        majors = [degrees.pop(0)]  # the next major becomes the primary one
    minors += [m for m in add_minor if m not in minors]
    for code in drop_minor:
        if code not in minors:
            raise ProfileError(f"no minor {code} to drop")
        minors.remove(code)
    changed["majors"], changed["additional_degrees"], changed["minors"] = majors, degrees, minors
    return changed


def describe_changes(switch_major: Optional[str] = None, add_major: Sequence[str] = (),
                     add_degree: Sequence[str] = (), drop_major: Sequence[str] = (),
                     add_minor: Sequence[str] = (), drop_minor: Sequence[str] = ()) -> str:
    """``"switch major to MATH; add minor RAS"``."""
    parts = [f"switch major to {switch_major}"] if switch_major else []
    parts += [f"add major {m}" for m in add_major] + [f"add a degree in {m}" for m in add_degree]
    parts += [f"drop major {m}" for m in drop_major] + [f"add minor {m}" for m in add_minor]
    parts += [f"drop minor {m}" for m in drop_minor]
    return "; ".join(parts) or "no change"


@dataclass(frozen=True)
class Outcome:
    """One version of the program, planned and audited."""
    profile: Profile
    schedule: Schedule
    report: AuditReport
    planned_credits: int
    credited_counting: Tuple[str, ...]  # credited courses a major or minor requirement counts

    @property
    def finish(self) -> str:
        return str(self.schedule.semesters[-1]) if self.schedule.semesters else "already done"

    @property
    def terms(self) -> int:
        return len(self.schedule.semesters)

    @property
    def met(self) -> int:
        return sum(r.satisfied for r in self.report.results)


@dataclass(frozen=True)
class Comparison:
    before: Outcome
    after: Outcome

    @property
    def added(self) -> Tuple[str, ...]:
        """Courses the changed plan takes that the current one doesn't, in plan order."""
        before = set(self.before.schedule.get_all_courses())
        return tuple(c for c in self.after.schedule.get_all_courses() if c not in before)

    @property
    def dropped(self) -> Tuple[str, ...]:
        """Courses the current plan takes that the changed one doesn't, in plan order."""
        after = set(self.after.schedule.get_all_courses())
        return tuple(c for c in self.before.schedule.get_all_courses() if c not in after)


def compare(optimizer: ScheduleOptimizer, before: Profile, after: Profile) -> Comparison:
    """Plan and audit ``before`` (the program as it is) and ``after`` (changed)."""
    return Comparison(_outcome(optimizer, before), _outcome(optimizer, after))


def _outcome(optimizer: ScheduleOptimizer, profile: Profile) -> Outcome:
    program = profile.program
    schedule = optimizer.optimize_schedule(program, profile.start_year, profile.start_semester)
    report = optimizer.audit(program, schedule)
    credited = program.student.credited_courses()
    owned = program.owned_requirements()
    counting = sorted({c for (owner, _), result in zip(owned, report.results)
                       if owner.kind in ("major", "minor") for c in result.applied if c in credited})
    return Outcome(profile, schedule, report, schedule.total_credits(optimizer.course_catalog),
                   tuple(counting))


def format_comparison(comparison: Comparison, description: str) -> str:
    """A side-by-side summary of the current and changed plans."""
    before, after = comparison.before, comparison.after
    rows: List[Tuple[str, str, str]] = [
        ("Programs", _programs(before.profile), _programs(after.profile)),
        ("Last term", before.finish, after.finish),
        ("Terms", str(before.terms), str(after.terms)),
        ("Planned credits", str(before.planned_credits), str(after.planned_credits)),
        ("Requirements met", f"{before.met} of {len(before.report.results)}",
         f"{after.met} of {len(after.report.results)}"),
    ]
    if before.profile.program.student.credited_courses():
        rows.append(("Credited courses in majors/minors", str(len(before.credited_counting)),
                     str(len(after.credited_counting))))
    width = max(len(r[0]) for r in rows)
    column = max(len(r[1]) for r in rows + [("", "Now", "")])
    lines = [f"What if: {description}", "",
             f"{'':{width}}  {'Now':{column}}  What if"]
    lines += [f"{label:{width}}  {now:{column}}  {then}" for label, now, then in rows]
    lost = [c for c in before.credited_counting if c not in after.credited_counting]
    if lost:
        lines += ["", f"Credited courses that would no longer count: {', '.join(lost)}"]
    lines += ["", f"Courses added ({len(comparison.added)}): {', '.join(comparison.added) or 'none'}",
              f"Courses dropped ({len(comparison.dropped)}): {', '.join(comparison.dropped) or 'none'}"]
    unmet = after.report.unmet
    if unmet:
        lines += ["", f"The changed plan leaves {len(unmet)} requirement(s) unmet:"]
        lines += [f"  - {r.requirement.name}: {r.reason}" for r in unmet]
    return "\n".join(lines)


def _programs(profile: Profile) -> str:
    program = profile.program
    parts = [" + ".join(m.major_code + (f" ({m.track})" if m.track else "")
                        for m in [program.primary_major, *program.additional_majors])]
    parts += [f"degree {m.major_code}" for m in program.additional_degrees]
    parts += [f"minor {m.minor_code}" for m in program.minors]
    return ", ".join(parts)


def _major(text: str) -> Any:
    code, _, track = text.partition(":")
    return {"code": code, "track": track} if track else code


def _code(entry: Any) -> str:
    return entry["code"] if isinstance(entry, dict) else str(entry)
