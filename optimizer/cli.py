"""
Command-line interface: ``umd-plan`` (or ``python main.py``).

    umd-plan plan PROFILE [--scenarios N] [--no-solver] [--json]
    umd-plan audit PROFILE [--json]
    umd-plan alternatives PROFILE COURSE... [--no-solver] [--json]

PROFILE is a student profile JSON file (see ``optimizer.data.profile``).
``plan`` prints the semester-by-semester plan and any requirement it leaves
unmet; ``audit`` checks what the student already has credit for, without a
plan; ``alternatives`` plans, then lists the courses that could replace each
named course in its term. ``--data-dir`` points at the catalog and requirement
files (default: the repository's ``sample_data``). Exit status: 0 on success,
1 when a plan leaves a requirement unmet, 2 for a bad profile or arguments.
Planner warnings go to stderr.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .core.audit import AuditReport, RequirementResult
from .core.optimizer import ScheduleOptimizer
from .data.loader import DataLoader
from .data.profile import Profile, ProfileError, load_profile
from .models.catalog import Catalog
from .models.schedule import Schedule

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="warning: %(message)s", stream=sys.stderr)
    loader = DataLoader(args.data_dir)
    catalog = loader.load_catalog()
    if not catalog:
        print(f"error: no courses in {args.data_dir / 'courses'}", file=sys.stderr)
        return 2
    try:
        profile = load_profile(args.profile, loader, catalog)
    except ProfileError as error:
        print(f"error: {args.profile}: {error}", file=sys.stderr)
        return 2
    optimizer = ScheduleOptimizer(catalog, use_solver=not getattr(args, "no_solver", False))
    return args.command(args, profile, optimizer)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="umd-plan", description="Plan a UMD student's courses semester by semester.")
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    def command(name: str, handler, help: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help, description=help)
        sub.add_argument("profile", type=Path, help="student profile JSON file")
        sub.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                         help="catalog and requirement files (default: %(default)s)")
        sub.add_argument("--json", action="store_true", help="print JSON instead of text")
        sub.set_defaults(command=handler)
        return sub

    plan = command("plan", _plan, "Plan every semester and report unmet requirements.")
    plan.add_argument("--scenarios", type=int, default=1, metavar="N",
                      help="up to N different plans, best first (default: 1)")
    plan.add_argument("--no-solver", action="store_true",
                      help="use the greedy plan only (faster; no OR-Tools)")
    command("audit", _audit, "Check requirements against the student's credited courses only.")
    alternatives = command("alternatives", _alternatives,
                           "Plan, then list courses that could replace the given ones in their term.")
    alternatives.add_argument("courses", nargs="+", metavar="COURSE", help="planned course codes")
    alternatives.add_argument("--no-solver", action="store_true",
                              help="use the greedy plan only (faster; no OR-Tools)")
    return parser


def _plan(args: argparse.Namespace, profile: Profile, optimizer: ScheduleOptimizer) -> int:
    program = profile.program
    plans = optimizer.generate_multiple_scenarios(
        program, max(args.scenarios, 1), start_year=profile.start_year,
        start_semester=profile.start_semester)
    reports = [optimizer.audit(program, plan) for plan in plans]
    catalog = optimizer.course_catalog
    if args.json:
        _print_json({"student": _student(profile), "plans": [
            {**_schedule_json(plan, catalog), "unmet": [_result_json(r) for r in report.unmet]}
            for plan, report in zip(plans, reports)]})
    else:
        print(_heading(profile))
        for number, (plan, report) in enumerate(zip(plans, reports), start=1):
            if len(plans) > 1:
                print(f"\n=== Plan {number} of {len(plans)} ===")
            print()
            print(_schedule_text(plan, catalog, program.student.credits_completed))
            print()
            print(_unmet_text(report))
    return 0 if all(report.satisfied for report in reports) else 1


def _audit(args: argparse.Namespace, profile: Profile, optimizer: ScheduleOptimizer) -> int:
    report = optimizer.audit(profile.program)
    if args.json:
        _print_json({"student": _student(profile),
                     "requirements": [_result_json(r) for r in report.results]})
        return 0
    print(_heading(profile))
    print(f"Credited: {', '.join(sorted(profile.program.student.credited_courses())) or 'nothing yet'}\n")
    for result in report.results:
        mark = "met " if result.satisfied else "    "
        detail = ", ".join(result.applied) if result.satisfied else result.reason
        print(f"  [{mark}] {result.requirement.name}" + (f": {detail}" if detail else ""))
    met = sum(r.satisfied for r in report.results)
    print(f"\n{met} of {len(report.results)} requirements met")
    return 0


def _alternatives(args: argparse.Namespace, profile: Profile,
                  optimizer: ScheduleOptimizer) -> int:
    program = profile.program
    schedule = optimizer.optimize_schedule(program, profile.start_year, profile.start_semester)
    planned = schedule.get_all_courses()
    missing = [c for c in args.courses if c not in planned]
    if missing:
        print(f"error: not in the plan: {', '.join(missing)} "
              f"(planned: {', '.join(planned)})", file=sys.stderr)
        return 2
    found = optimizer.course_alternatives(program, schedule, args.courses)
    catalog = optimizer.course_catalog
    if args.json:
        _print_json({code: [_course_json(c, catalog) for c in options]
                     for code, options in found.items()})
        return 0
    terms = {c: str(s) for s in schedule.semesters for c in s.courses}
    for code, options in found.items():
        print(f"{code} ({terms[code]}): " + (
            f"{len(options)} alternative{'s' * (len(options) != 1)}" if options
            else "no alternative fits in that term without other changes"))
        for option in options:
            course = catalog[option]
            restricted = "  (restricted)" if course.restrictions else ""
            print(f"  {option:10} {course.name[:48]:48} {course.credits:>2} cr{restricted}")
    return 0


def _heading(profile: Profile) -> str:
    program = profile.program
    student = program.student

    parts = [" + ".join(m.major_name for m in [program.primary_major, *program.additional_majors])]
    parts += [f"another degree: {m.major_name}" for m in program.additional_degrees]
    parts += [f"minor: {m.minor_name}" for m in program.minors]
    name = student.name or student.student_id or "Student"
    return f"{name}: {'; '.join(parts)}"


def _schedule_text(schedule: Schedule, catalog: Catalog, earned: int = 0) -> str:
    lines = []
    for semester in schedule.semesters:
        lines.append(f"{semester}  ({semester.total_credits(catalog)} credits)")
        for code in semester.courses:
            course = catalog.get(code)
            name = course.name[:48] if course else "(not in the catalog)"
            credits = course.credits if course else 0
            lines.append(f"  {code:10} {name:48} {credits:>2} cr")
    lines.append(f"Total: {schedule.total_credits(catalog)} credits in "
                 f"{len(schedule.semesters)} terms"
                 + (f", plus {earned} already earned" if earned else ""))
    return "\n".join(lines)


def _unmet_text(report: AuditReport) -> str:
    if report.satisfied:
        return f"All {len(report.results)} requirements met."
    lines = [f"{len(report.unmet)} of {len(report.results)} requirements unmet:"]
    lines += [f"  - {r.requirement.name}: {r.reason}" for r in report.unmet]
    return "\n".join(lines)


def _student(profile: Profile) -> Dict[str, Any]:
    program = profile.program
    return {"name": program.student.name, "id": program.student.student_id,
            "majors": [m.major_code for m in [program.primary_major, *program.additional_majors]],
            "additional_degrees": [m.major_code for m in program.additional_degrees],
            "minors": [m.minor_code for m in program.minors]}


def _course_json(code: str, catalog: Catalog) -> Dict[str, Any]:
    course = catalog.get(code)
    return {"code": code, "name": course.name if course else None,
            "credits": course.credits if course else 0}


def _schedule_json(schedule: Schedule, catalog: Catalog) -> Dict[str, Any]:
    return {"semesters": [{"term": s.type.value, "year": s.year,
                           "credits": s.total_credits(catalog),
                           "courses": [_course_json(c, catalog) for c in s.courses]}
                          for s in schedule.semesters],
            "total_credits": schedule.total_credits(catalog)}


def _result_json(result: RequirementResult) -> Dict[str, Any]:
    return {"id": result.requirement.id, "name": result.requirement.name,
            "satisfied": result.satisfied, "applied": list(result.applied),
            "credits": result.credits, "reason": result.reason}


def _print_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    sys.exit(main())
