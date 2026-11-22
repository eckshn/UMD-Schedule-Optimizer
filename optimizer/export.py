"""
Export plans as Markdown, CSV or iCalendar (``umd-plan plan --format``).

- ``to_markdown``: a heading per plan and per semester, with a table of its
  courses and the requirements the plan leaves unmet.
- ``to_csv``: one row per planned course: plan, term, year, code, title, credits.
- ``to_ical``: one all-day event per course spanning its term, for calendar
  apps. Term dates are approximate (``TERM_DATES``): UMD's calendar shifts by
  a few days each year, so check the registrar's before relying on them.
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .core.audit import AuditReport
from .models.catalog import Catalog
from .models.course import Course
from .models.schedule import Schedule, SemesterType

# (month, day) a term's classes start and its finals end, roughly
TERM_DATES: Dict[SemesterType, Tuple[Tuple[int, int], Tuple[int, int]]] = {
    SemesterType.WINTER: ((1, 2), (1, 22)),
    SemesterType.SPRING: ((1, 26), (5, 20)),
    SemesterType.SUMMER: ((6, 1), (8, 14)),
    SemesterType.FALL: ((8, 31), (12, 19)),
}


def to_markdown(plans: Sequence[Schedule], catalog: Mapping[str, Course], title: str = "Course plan",
                reports: Optional[Sequence[AuditReport]] = None, earned: int = 0) -> str:
    """Markdown for ``plans`` (best first); ``reports`` (one per plan) add the unmet requirements."""
    catalog = Catalog.of(catalog)
    lines = [f"# {title}"]
    for number, plan in enumerate(plans, start=1):
        level = "##"
        if len(plans) > 1:
            lines += ["", f"## Plan {number} of {len(plans)}"]
            level = "###"
        for semester in plan.semesters:
            lines += ["", f"{level} {semester} ({semester.total_credits(catalog)} credits)", "",
                      "| Course | Title | Credits |", "|---|---|---:|"]
            for code in semester.courses:
                course = catalog.get(code)
                name = _cell(course.name) if course else "(not in the catalog)"
                lines.append(f"| {code} | {name} | {course.credits if course else 0} |")
        lines += ["", f"**Total:** {plan.total_credits(catalog)} credits in {len(plan.semesters)} terms"
                  + (f", plus {earned} already earned." if earned else ".")]
        if reports is not None:
            report = reports[number - 1]
            if report.satisfied:
                lines.append(f"All {len(report.results)} requirements met.")
            else:
                lines += ["", f"{len(report.unmet)} of {len(report.results)} requirements unmet:", ""]
                lines += [f"- {_cell(r.requirement.name)}: {_cell(r.reason)}" for r in report.unmet]
    return "\n".join(lines) + "\n"


def to_csv(plans: Sequence[Schedule], catalog: Mapping[str, Course]) -> str:
    """CSV with a header row and one row per planned course."""
    catalog = Catalog.of(catalog)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["plan", "term", "year", "code", "title", "credits"])
    for number, plan in enumerate(plans, start=1):
        for semester in plan.semesters:
            for code in semester.courses:
                course = catalog.get(code)
                writer.writerow([number, semester.type.value, semester.year, code,
                                 course.name if course else "", course.credits if course else 0])
    return out.getvalue()


def to_ical(plan: Schedule, catalog: Mapping[str, Course],
            stamp: Optional[datetime] = None) -> str:
    """
    An iCalendar (RFC 5545) file with an all-day event per course over its
    term (``TERM_DATES``). ``stamp`` is the DTSTAMP (default: now, UTC).
    """
    catalog = Catalog.of(catalog)
    stamp = (stamp or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UMD Schedule Optimizer//umd-plan//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:Course plan"]
    for semester in plan.semesters:
        (start_month, start_day), (end_month, end_day) = TERM_DATES[semester.type]
        start = date(semester.year, start_month, start_day)
        end = date(semester.year, end_month, end_day) + timedelta(days=1)  # DTEND is exclusive
        for code in semester.courses:
            course = catalog.get(code)
            summary = f"{code} {course.name}" if course else code
            credits = f"{course.credits} credits, " if course else ""
            lines += ["BEGIN:VEVENT",
                      f"UID:{code}-{semester.type.value}-{semester.year}@umd-schedule-optimizer",
                      f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{end:%Y%m%d}",
                      f"SUMMARY:{_ical_text(summary)}",
                      f"DESCRIPTION:{_ical_text(f'{credits}{semester} (approximate term dates)')}",
                      "TRANSP:TRANSPARENT",
                      "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _ical_text(text: str) -> str:
    """Escape an iCalendar TEXT value."""
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Fold a content line to at most 75 octets per line (RFC 5545 3.1)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: List[str] = []
    current = b""
    for char in line:
        piece = char.encode("utf-8")
        if len(current) + len(piece) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += piece
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)
