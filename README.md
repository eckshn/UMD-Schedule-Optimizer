# UMD Schedule Optimizer

Builds a 4-year course plan for University of Maryland students. It schedules a degree's required courses across Fall/Spring semesters while respecting:

- prerequisites
- the terms each course is offered
- per-semester credit limits
- gen-ed requirements
- credit the student already has (completed, AP, transfer)

> Status: prototype. The scheduler is a simple greedy algorithm, and generated plans aren't guaranteed to be complete or valid yet.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

```bash
uv run python prototype_cli.py     # plan for a sample CS student, using sample_data/majors/CMSC.json
uv run python examples/example_full.py   # end-to-end example
uv run pytest                      # run the tests
```

Programmatic use:

```python
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.student import StudentProfile, StudentDegreeProgram

loader = DataLoader(Path("sample_data"))
student = StudentProfile(student_id="1", name="Terp", primary_major="CMSC",
                         ap_credits={"AP Calculus AB": "MATH140"})
program = StudentDegreeProgram(student=student, primary_major=loader.load_major("CMSC"),
                               minors=[loader.load_minor("RAS")])

schedule = ScheduleOptimizer(loader.load_all_courses()).optimize_schedule(program)
print(schedule)
```

## Layout

| Path | What |
|---|---|
| `optimizer/models/` | Dataclasses for courses, prerequisites, requirements, students and schedules |
| `optimizer/core/` | Prerequisite graph (networkx), constraint validation, and the scheduler |
| `optimizer/data/loader.py` | Loads the JSON data below |
| `sample_data/courses/` | Course catalogs (`CMSC`, `MATH`, and `GENED`, which holds every course with a gen-ed) |
| `sample_data/majors/`, `sample_data/minors/` | Degree requirements (`CMSC` General Track, `RAS` Robotics minor) |
| `sample_data/gen_eds/` | University-wide gen-ed requirements (`UMD`) |
| `tests/` | pytest suite |
| `prototype_cli.py` | Prototype CLI (main entry point); `main.py` is a stub |
| `examples/` | Example scripts |
| `scripts/` | Ad-hoc debugging scripts (`debug_*`, `check_*`, `trace_optimizer`) |
| `scrapers/` | Scrapers for UMD course data and the `GENED.json` generator |
| `data/` | Raw scraper output (`testudo_courses/`, `scraped_courses/`), department lists, scrape logs |
| `docs/` | Design notes, bug-fix history; `docs/requirements/` holds UMD requirement source material |

Run everything from the repo root (data paths are relative to it). `uv sync` installs `optimizer` in editable mode, so scripts can be run by path: `uv run python scripts/check_cycles.py`.

## Course data

Course data comes from two UMD sources:

- **Testudo Schedule of Classes**: gen-eds and current offerings. Output goes to `data/testudo_courses/`. See [scrapers/README.md](scrapers/README.md).

  ```bash
  uv run python scrapers/scrape_testudo.py CMSC MATH     # or --all
  uv run python scrapers/generate_gened.py               # rebuild sample_data/courses/GENED.json
  ```

- **Academic Catalog**: full course descriptions, written to `data/scraped_courses/`.

  ```bash
  uv run python scrapers/scrape_umd_catalog.py CMSC
  ```

## Requirement file format

Majors and minors are JSON files. Each requirement object uses the field names of `optimizer.models.requirements.Requirement`. Its `type` is one of `course`, `choice`, `group`, `category`, `credit_hours` or `gen_ed`. Requirements can be nested inside `courses`/`choices`. The shorthand `{"code": "CMSC131"}` means a single required course. See `sample_data/majors/CMSC.json` and `sample_data/minors/RAS.json` for examples. Each type must set its own field: `course_code` for `course`, `choices` for `choice`, `courses` for `group` (may be empty), and `gen_ed_category` for `gen_ed`.

Gen-ed requirements apply university-wide, so they are not part of any major. They live in `sample_data/gen_eds/UMD.json` as `{"requirements": [...]}`. Load them with `DataLoader.load_gen_eds()` and pass them as `StudentDegreeProgram(gen_ed_requirements=...)`. They are processed after every major and minor requirement.
