"""
Human-readable degree audit: what's met (and by which courses, when they were
or will be taken), what's missing, why, and what could fill it.

``format_audit`` lays out a ``ScheduleOptimizer.audit`` report by program:
each major (with its benchmarks), each minor, general education, the degree's
credit minimums (and unique credits, with several degrees), then requested
courses. Requirements that ask for nothing (the CS "Area" groups, which only
label courses for the 400-level requirement) are left out.
"""

from typing import List, Mapping, Optional, Tuple

from .core.audit import AuditReport, RequirementResult
from .models.catalog import Catalog
from .models.course import Course
from .models.requirements import Requirement, RequirementType
from .models.schedule import Schedule
from .models.student import StudentDegreeProgram

MET, UNMET = "✓", "✗"
MAX_OPTIONS = 8  # options listed for an unmet requirement before "+N more"


def format_audit(program: StudentDegreeProgram, report: AuditReport,
                 catalog: Mapping[str, Course], schedule: Optional[Schedule] = None) -> str:
    """
    The audit as text. ``report`` is ``ScheduleOptimizer.audit(program,
    schedule)``: one row per ``program.owned_requirements()``, then the
    benchmarks, then the requested courses. Pass the same ``schedule`` so
    courses show the term they're planned for.
    """
    return _Formatter(program, report, Catalog.of(catalog), schedule).text()


class _Formatter:
    def __init__(self, program: StudentDegreeProgram, report: AuditReport, catalog: Catalog,
                 schedule: Optional[Schedule]):
        self.program = program
        self.catalog = catalog
        self.schedule = schedule
        semesters = schedule.semesters if schedule else []
        self.term = {c: str(s) for s in semesters for c in s.courses}
        self.when = {c: i for i, s in enumerate(semesters) for c in s.courses}  # credited: -1
        student = program.student
        self.grades = student.grades()
        self.ap = set(student.ap_credits.values())
        self.transfer = set(student.transfer_credits)
        self.taken = student.credited_courses() | set(self.term)

        owned = program.owned_requirements()
        results = list(report.results)
        if len(results) < len(owned):
            raise ValueError("report has fewer rows than the program has requirements")
        self.owned = list(zip((o for o, _ in owned), results))
        self.extra = {r.requirement.id: r for r in results[len(owned):]}

    def text(self) -> str:
        sections: List[Tuple[str, List[RequirementResult]]] = []
        for owner, major in self.program.major_owners():
            rows = [r for o, r in self.owned if o == owner
                    and r.requirement.type != RequirementType.UNIQUE_CREDITS]
            sections.append((f"{major.major_name} (major)", rows))
            benchmarks = [self.extra.pop(b.id) for _, b in major.benchmark_requirements()
                          if b.id in self.extra]
            if benchmarks:
                sections.append(("  Limited-enrollment benchmarks", benchmarks))
        for minor in self.program.minors:
            sections.append((f"{minor.minor_name} (minor)",
                             [r for o, r in self.owned if o.kind == "minor" and o.code == minor.minor_code]))
        degree = [r for o, r in self.owned if o.kind == "degree"]
        sections.append(("General education",
                         [r for r in degree if r.requirement.type == RequirementType.GEN_ED]))
        sections.append(("Degree", [r for r in degree if r.requirement.type != RequirementType.GEN_ED]
                         + [r for _, r in self.owned
                            if r.requirement.type == RequirementType.UNIQUE_CREDITS]))
        requested = [self.extra.pop(f"requested_{r.code}") for r in self.program.student.requested_courses
                     if f"requested_{r.code}" in self.extra]
        sections.append(("Requested courses", requested))
        sections.append(("Other", list(self.extra.values())))

        shown = [(title, [r for r in rows if not _asks_nothing(r.requirement)])
                 for title, rows in sections]
        shown = [(title, rows) for title, rows in shown if rows]
        all_rows = [r for _, rows in shown for r in rows]
        met = sum(r.satisfied for r in all_rows)
        lines = [self._heading(), f"{met} of {len(all_rows)} requirements met"
                 + ("." if met == len(all_rows) else f"; {len(all_rows) - met} to go.")]
        for title, rows in shown:
            lines += ["", title]
            indent = "    " if title.startswith("  ") else "  "
            for result in rows:
                lines += self._result(result, indent)
        return "\n".join(lines)

    def _heading(self) -> str:
        student = self.program.student
        who = student.name or student.student_id or "Student"
        if self.schedule and self.schedule.semesters:
            first, last = self.schedule.semesters[0], self.schedule.semesters[-1]
            scope = (f"plan {first} to {last}, {self.schedule.total_credits(self.catalog)} "
                     f"planned credits")
        else:
            scope = "credited courses only"
        earned = f", {student.credits_completed} credits earned" if student.credits_completed else ""
        return f"Degree audit for {who} ({scope}{earned})"

    def _result(self, result: RequirementResult, indent: str) -> List[str]:
        requirement = result.requirement
        mark = MET if result.satisfied else UNMET
        lines = [f"{indent}{mark} {requirement.name}"]
        detail = indent + "    "
        if requirement.type == RequirementType.CREDIT_HOURS:
            lines[0] += f": {result.credits} of {requirement.min_credits} credits"
        elif result.applied:
            ordered = sorted(result.applied, key=lambda c: self.when.get(c, -1))  # credited first
            lines.append(detail + ", ".join(self._course(c) for c in ordered))
        if not result.satisfied:
            if result.reason and requirement.type != RequirementType.CREDIT_HOURS:
                reason = result.reason
                label = "Missing" if reason.startswith("missing ") else "Why"
                lines.append(f"{detail}{label}: {reason[len('missing '):] if label == 'Missing' else reason}")
            if requirement.notes:
                lines.append(f"{detail}Note: {requirement.notes}")
            options = self._options(requirement, result)
            if options:
                lines.append(f"{detail}Could take: {options}")
            for nested in result.nested:
                lines += self._result(nested, detail)
        return lines

    def _course(self, code: str) -> str:
        """``CMSC131 (A)``, ``MATH140 (AP)``, ``CMSC330 (Fall 2026)``."""
        if code in self.term:
            return f"{code} ({self.term[code]})"
        if code in self.ap:
            return f"{code} (AP)"
        if code in self.transfer:
            return f"{code} (transfer)"
        if code in self.grades:
            return f"{code} ({self.grades[code]})"
        return code

    def _options(self, requirement: Requirement, result: RequirementResult) -> str:
        """
        Listed courses of an unmet GROUP/CHOICE that picks some of them, which
        the student hasn't taken or planned (a GROUP needing every course
        names the missing ones in its reason already).
        """
        needs_all = (requirement.type == RequirementType.GROUP and requirement.min_courses is None
                     and not requirement.min_credits)
        if requirement.type not in (RequirementType.GROUP, RequirementType.CHOICE) or needs_all:
            return ""
        codes = [c for c in dict.fromkeys(requirement.listed_courses())
                 if c in self.catalog and c not in result.applied
                 and not self.catalog.has_equivalent_in(c, self.taken)]
        if not codes:
            return ""
        more = len(codes) - MAX_OPTIONS
        return ", ".join(codes[:MAX_OPTIONS]) + (f" (+{more} more)" if more > 0 else "")


def _asks_nothing(requirement: Requirement) -> bool:
    """A GROUP needing no courses and no credits (it only labels courses, e.g. CS areas)."""
    return (requirement.type == RequirementType.GROUP and requirement.min_courses == 0
            and not requirement.min_credits and not requirement.min_areas)
