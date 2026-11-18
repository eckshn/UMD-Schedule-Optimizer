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
                               minors=[loader.load_minor("RAS")],
                               gen_ed_requirements=loader.load_gen_eds())

optimizer = ScheduleOptimizer(loader.load_catalog())
schedule = optimizer.optimize_schedule(program)
print(schedule)
print([r.requirement.id for r in optimizer.audit(program, schedule).unmet])  # what's still missing
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

## Implementation plan

Check items off as they land.

### Phase 1: Core planner
- [x] Data models for courses, prerequisite trees (COURSE/OR/AND), requirements, students and schedules
- [x] JSON loader for course catalogs, majors, minors and gen-eds (Testudo-style string prerequisites too)
- [x] Prerequisite graph with deterministic topological sort
- [x] Greedy Fall/Spring assignment that respects prerequisites, term offerings and credit load
- [x] Completed, AP and transfer credit counted toward prerequisites and removed from the plan
- [x] Deterministic output across `PYTHONHASHSEED`s (enforced by a test)
- [x] `Catalog` with honors/base and cross-listed course equivalence
- [x] UMD policy rules in `rules.py`: 3 upper-level CMSC per semester, FSPW after 60 credits, DSNL→DSNS

### Phase 2: Requirements
- [x] COURSE, CHOICE, GROUP (min courses/credits/areas, max per area) and GEN_ED requirements
- [x] No double counting across major requirements; gen-eds reuse major courses with option locking (`GenEdLedger`)
- [x] University-wide gen-eds in `gen_eds/UMD.json`, processed after majors and minors
- [x] `CourseSelector` extracted; `audit_requirements` is the single check of whether requirements are met
- [x] CS major, General Track (`majors/CMSC.json`) and Robotics minor (`minors/RAS.json`)
- [ ] CATEGORY requirements (rule-based: level range, department, exclusions), selected and audited
- [ ] CS Upper Level Concentration: 12 credits of 300–400 level in one non-CMSC discipline (only unmet requirement on the CS plan)
- [ ] `additional_math_stat` and `statistics` expressed as rules (MATH/STAT with a MATH141 prerequisite) instead of fixed lists
- [ ] CREDIT_HOURS requirements checked in the audit (120 total, 30 upper-level major credits)
- [ ] Free electives to reach 120 credits
- [ ] Benchmarks for limited-enrollment programs (`MajorRequirements.benchmarks`)
- [ ] Double-major and minor overlap rules (`double_count_rules`, `double_count_limit`)
- [ ] Other CS tracks and more majors/minors

### Phase 3: Course data
- [x] Testudo Schedule of Classes scraper (gen-eds, offerings)
- [x] Academic Catalog scraper (descriptions)
- [x] `GENED.json` generated from Testudo data, merged with department files
- [ ] Department files beyond CMSC/MATH in `sample_data/courses/` (STAT, ENEE, ENME, ENAE for the RAS minor, …)
- [ ] Preserve hand-added prerequisites across `generate_gened.py` rebuilds
- [ ] Offering history across several terms (real Fall/Spring frequency)

### Phase 4: Better schedules
- [ ] Credit balancing across semesters (the greedy pass fills semesters unevenly)
- [ ] Enforce corequisites (loaded but not checked)
- [ ] Optional Summer/Winter terms
- [ ] Constraint solver (e.g. OR-Tools CP-SAT) with weighted objectives: fewer semesters, balanced load, fewer prerequisite delays
- [ ] Several alternative plans per student
- [ ] Minimum grade requirements (all completed courses are treated as an A today)

### Phase 5: Usability
- [ ] Real CLI entry point (`main.py`) that reads a student profile from JSON
- [ ] Human-readable audit report: what's met, what's missing and why
- [ ] Export plans (Markdown/CSV/iCal)
- [ ] What-if analysis (switching majors, adding a minor)

### Phase 6: Web app
- [ ] API layer (FastAPI)
- [ ] Database for catalog, requirements and saved plans
- [ ] Frontend with drag-and-drop semester editing and live re-validation
- [ ] Auth and deployment
