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
from optimizer.models.student import CourseRequest, StudentProfile, StudentDegreeProgram

loader = DataLoader(Path("sample_data"))
student = StudentProfile(student_id="1", name="Terp", primary_major="CMSC",
                         ap_credits={"AP Calculus AB": "MATH140"},
                         # courses to fit in, optionally by a deadline (see "Requested courses")
                         requested_courses=["CMSC422", CourseRequest("PHYS161", by_semester=3)])
program = StudentDegreeProgram(student=student, primary_major=loader.load_major("CMSC"),  # or ("CMSC", "machine_learning")
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
| `sample_data/courses/` | Course catalogs: hand-curated `CMSC` and `MATH`; `MATH_generated` (the rest of MATH), `STAT`, `AMSC`, `PHYS`, `ENEE`, `ENME`, `ENAE`, `ENES`, `BIOM` generated from Testudo; `GENED`, which holds every course with a gen-ed |
| `sample_data/majors/`, `sample_data/minors/` | Degree requirements (`CMSC` with five tracks, `MATH` with three, `RAS` Robotics minor) |
| `sample_data/gen_eds/` | University-wide gen-ed requirements (`UMD`) |
| `tests/` | pytest suite |
| `prototype_cli.py` | Prototype CLI (main entry point); `main.py` is a stub |
| `examples/` | Example scripts |
| `scripts/` | Ad-hoc debugging scripts (`debug_*`, `check_*`, `trace_optimizer`) |
| `scrapers/` | Scrapers for UMD course data and the `GENED.json` generator |
| `data/` | Raw scraper output (`testudo_courses/`, `testudo_terms/{term}/`, `scraped_courses/`), department lists, scrape logs |
| `docs/` | Design notes, bug-fix history; `docs/requirements/` holds UMD requirement source material |

Run everything from the repo root (data paths are relative to it). `uv sync` installs `optimizer` in editable mode, so scripts can be run by path: `uv run python scripts/check_cycles.py`.

## Course data

Course data comes from two UMD sources:

- **Testudo Schedule of Classes**: gen-eds and current offerings. Output goes to `data/testudo_courses/`. See [scrapers/README.md](scrapers/README.md).

  ```bash
  uv run python scrapers/scrape_testudo.py CMSC MATH     # or --all
  uv run python scrapers/generate_gened.py               # rebuild sample_data/courses/GENED.json
  ```

- **Department files**: scrape each term into `data/testudo_terms/{term}/`, then generate `sample_data/courses/{DEPT}.json`. Offerings come from the terms a course appears in, and prerequisite sentences are parsed into AND/OR trees (`optimizer/data/prerequisite_text.py`). Hand-curated files (CMSC, MATH) are never overwritten without `--force`.

  ```bash
  for t in 202508 202601 202608 202701; do
    uv run python scrapers/scrape_testudo.py ENME ENEE --term $t --output data/testudo_terms/$t --format json
  done
  uv run python scrapers/generate_departments.py ENME ENEE
  ```

  For a department with a hand-curated file (MATH), the generator writes the courses it lacks to `MATH_generated.json`.

- **Academic Catalog**: full course descriptions, written to `data/scraped_courses/`.

  ```bash
  uv run python scrapers/scrape_umd_catalog.py CMSC
  ```

## Requirement file format

Majors and minors are JSON files. Each requirement object uses the field names of `optimizer.models.requirements.Requirement`. Its `type` is one of `course`, `choice`, `group`, `category`, `credit_hours` or `gen_ed`. Requirements can be nested inside `courses`/`choices`. The shorthand `{"code": "CMSC131"}` means a single required course. See `sample_data/majors/CMSC.json` and `sample_data/minors/RAS.json` for examples. Each type must set its own field: `course_code` for `course`, `choices` for `choice`, `courses` for `group` (may be empty), `gen_ed_category` for `gen_ed`, `min_courses` or `min_credits` for `category`, and `min_credits` for `credit_hours`.

A `category` requirement is a rule instead of a course list. Any course passing all the filters it sets counts:

| Field | Meaning |
|---|---|
| `min_level`, `max_level` | Course number range, inclusive (`300`–`499`) |
| `departments` | Only these department prefixes (`["MATH", "STAT"]`) |
| `exclude_departments` | Not these departments, nor courses cross-listed with them |
| `pattern` | Regex the course code must match from its start |
| `has_prerequisite` | Every way of meeting the course's prerequisites goes through this course, directly or transitively (`"MATH141"`) |
| `single_department` | All counted courses must come from one department |
| `max_independent_study_credits` | At most this many credits from independent study or experiential learning courses (recognized by name, e.g. "Experiential Learning", "Internship", "Honors Thesis") |

Any requirement can also set `"exclusive": false`. Its courses then stay available to later requirements, such as a minor's or a second major's, though it still can't use courses an earlier requirement took.

A `distribution` requirement takes the same filters plus `min_areas` (and optionally `max_from_same_area`). It checks that the courses its program counted toward earlier requirements, among those passing the filters, span that many areas (`Course.areas`). The CS specializations use it for "upper-level courses from at least 3 areas". A `group` can also set `min_areas_ignore` (areas that don't count toward its `min_areas`) and `mutually_exclusive` (sets of courses of which at most one counts, such as two capstones).

A `credit_hours` requirement can also set `min_courses` ("eight 400-level MATH/AMSC/STAT courses"). A `choice` whose choices are nested requirements (alternative course sequences) is planned with the option needing the fewest new courses.

A `credit_hours` requirement takes the same filters but sums the credits of *every* matching course, including courses already counted toward other requirements. A major's `min_credits` and `min_upper_level_credits` become `credit_hours` requirements automatically (`total_credits`, `upper_level_credits`).

The CS Upper Level Concentration ("12 credits of 300–400 level courses in one discipline outside CS", at most 3 of them independent study, may overlap with a minor) is `{"type": "category", "min_level": 300, "max_level": 499, "exclude_departments": ["CMSC"], "single_department": true, "min_credits": 12, "max_independent_study_credits": 3, "exclusive": false}`.

A major can list limited-enrollment benchmarks: `"benchmarks": {"45": [...], "75": [...]}` maps a credit count to requirements that must be met by the end of the semester in which the student reaches that many credits. `ScheduleOptimizer.audit` reports each as `{major_code}_benchmark_{credits}` after the degree requirements. Minimum grades and GPA aren't checked yet.

### Requested courses

### Summer and Winter terms

Plans have 8 Fall/Spring semesters. `StudentProfile(include_summer=True)` adds a Summer term between each Spring and Fall, and `include_winter=True` a Winter term between each Fall and Spring (Winter 2026 follows Fall 2025). Students usually take one course in a Summer or Winter term, so each holds one course by default: the highest-priority course offered then, which for Winter is a short list. `summer_max_courses`/`winter_max_courses` raise that, within `summer_max_credits` (default 8, one summer session) and `winter_max_credits` (default 4). UMD caps them at 16 (8 per session) and 4 credits without the advising college's approval (`rules.MAX_TERM_CREDITS`). Summer and Winter have no credit minimum and aren't evened out with the regular semesters. With full summers (`summer_max_courses=4, summer_max_credits=16`) and winters, a CS student can finish in three years. Only the department files have Summer/Winter offerings; gen-ed courses from `GENED.json` count as Fall/Spring only.

A student can ask for courses no requirement calls for, or set a deadline on one: `StudentProfile(requested_courses=["CMSC422", CourseRequest("PHYS161", by_semester=3), CourseRequest("STAT400", by_credits=60)])`. A plain code means "some time before graduating". `by_semester` counts Fall/Spring semesters from the plan's first (1 = the first), and `by_credits` means by the end of the semester in which cumulative credits reach that number. The plan includes every requested course and lets requirements count it, so requesting CMSC422 makes it one of the CS electives instead of adding a course. Courses with a deadline are scheduled early, like benchmark courses. Those without one fill the room required courses leave, before free electives. `ScheduleOptimizer.audit` adds a `requested_{code}` row for each request, last. The greedy scheduler can't always meet a deadline (CMSC351 can't come before the fourth semester for a freshman), so a missed one is reported there and logged as a warning.

A major or minor can give courses different prerequisites for its own students: `"prerequisite_overrides": {"CMSC477": [...]}` maps a course to a prerequisite list in the course-file format, which replaces the catalog's when the student is in that program (RAS students take CMSC477 after ENEE467 and linear algebra; the catalog keeps the non-minor CMSC420 path). If several of the student's programs override the same course, meeting any one of them is enough.

A student can have any number of majors (`StudentDegreeProgram(primary_major=..., additional_majors=[...])`) and minors. Majors may share courses with each other. Otherwise a course counts toward one program, except that a minor may share up to 6 credits with the majors, or the credits of its two largest shared courses if more, so two 4-credit courses are fine but 3+3+2 is not (UMD minor policy, "six credits (or two courses)", in `optimizer/core/rules.py`). A minor's `"max_overlap_with_major"` can also cap the number of courses. Courses used by one minor can't count toward another. Courses a non-exclusive requirement uses (the CS Upper Level Concentration) don't count as overlap.

### Tracks

Majors don't need tracks. A major with specializations lists the requirements every track shares at the top level and each track's own under `"tracks"`:

```json
{"major_code": "CMSC", "lower_level": [...], "upper_level": [...], "concentration": {...},
 "default_track": "general",
 "tracks": {"data_science": {"major_name": "...", "upper_level": [...],
                             "supporting_courses": [{"id": "statistics", "type": "course", "course_code": "STAT400"}]}}}
```

A track requirement with the same `id` (or `code`) as a shared one replaces it; others are appended. `DataLoader.load_major("CMSC", "data_science")` loads a track, and `load_major("CMSC")` loads the default. `major_tracks("CMSC")` lists them.

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
- [x] UMD policy rules in `rules.py`: 3 upper-level CMSC per semester, FSPW after 60 credits and after Academic Writing, DSNL→DSNS

### Phase 2: Requirements
- [x] COURSE, CHOICE, GROUP (min courses/credits/areas, max per area) and GEN_ED requirements
- [x] No double counting across major requirements; gen-eds reuse major courses with option locking (`GenEdLedger`)
- [x] University-wide gen-eds in `gen_eds/UMD.json`, processed after majors and minors
- [x] `CourseSelector` extracted; `audit_requirements` is the single check of whether requirements are met
- [x] CS major, General Track (`majors/CMSC.json`) and Robotics minor (`minors/RAS.json`)
- [x] CATEGORY requirements (rule-based: level range, department, exclusions), selected and audited
- [x] CS Upper Level Concentration: 12 credits of 300–400 level in one non-CMSC discipline
- [x] Concentration limits: at most 3 credits of independent study, overlap with a minor allowed
- [x] `additional_math_stat` and `statistics` expressed as rules (MATH/STAT with a MATH141 prerequisite) instead of fixed lists
- [x] CREDIT_HOURS requirements checked in the audit (120 total, 30 upper-level credits)
- [x] ~~Minimum major credits (`min_major_credits`)~~: not a UMD CS rule (the old value 54 had no source), so CS doesn't set it; it stays unchecked until a major needs it
- [x] Free electives to reach 120 credits
- [x] Benchmarks for limited-enrollment programs (`MajorRequirements.benchmarks`): audited, and the scheduler places benchmark courses first (grades and GPA not checked)
- [x] Minor overlap: a minor may share at most 6 credits with the majors, or the credits of its two largest shared courses if more (UMD: "six credits (or two courses)"; `max_overlap_with_major` can cap the course count), minors never share with each other, and the selector reuses major courses for minors
- [x] Any number of majors (`additional_majors`) and minors
- [x] Double-major overlap: majors may share courses with each other without a limit (`rules.MAY_SHARE`)
- [x] CS specializations as tracks of `majors/CMSC.json`: General, Cybersecurity, Data Science, Machine Learning, Quantum Information
- [x] Mathematics major: Traditional, Statistics and Applied tracks (`majors/MATH.json`), with the honors MATH340-341 alternative to MATH240-241-246; CS + Math double major fits in 8 semesters
- [x] Prerequisite substitutes (MATH340/341 meet prerequisites naming MATH241/240/246) and credit overlaps ("credit only granted for": a plan never takes both MATH240 and MATH461)
- [ ] Mathematics Secondary Education track (needs the College of Education's course list)
- [ ] More majors and minors (needs their requirement files and department course data)

### Phase 3: Course data
- [x] Testudo Schedule of Classes scraper (gen-eds, offerings)
- [x] Academic Catalog scraper (descriptions)
- [x] `GENED.json` generated from Testudo data, merged with department files
- [x] Department files beyond CMSC/MATH: STAT, AMSC, PHYS, ENEE, ENME, ENAE, ENES, generated from Testudo terms Fall 2025 to Spring 2027 (Winter and Summer included) with parsed prerequisite text (`scrapers/generate_departments.py`)
- [ ] More department files (each needs a Testudo scrape per term, then `generate_departments.py`)
- [x] Program-specific prerequisites (`prerequisite_overrides`: RAS students take CMSC477 after ENEE467 and linear algebra; the catalog lists the non-minor prerequisites)
- [x] Preserve hand-added prerequisites across `generate_gened.py` rebuilds: the ENGL101 prerequisite of Professional Writing courses is now a rule (`rules.GEN_ED_PREREQUISITES`) applied when the catalog loads, so `GENED.json` is exactly what the script writes
- [x] Offering history across the same terms for the hand-curated CMSC/MATH files (`generate_departments.py --offered-only`)

### Phase 4: Better schedules
- [x] Credit balancing across semesters: after the greedy pass, `optimizer/core/balance.py` moves (or swaps) courses from heavier to lighter semesters while the plan stays valid, so a CS plan runs 15–16 credits every semester instead of ending with 9
- [x] Enforce corequisites: met by a course taken earlier or in the same semester; the scheduler places a course together with a planned corequisite it still needs (PHYS270 with PHYS271), and generated departments parse Testudo's corequisite text ("ENAE481 or ENAE483")
- [x] Optional Summer/Winter terms (`include_summer`/`include_winter`, one course each by default, at most 16 Summer and 4 Winter credits), with real Summer/Winter offerings scraped for the department files
- [ ] Constraint solver (e.g. OR-Tools CP-SAT) with weighted objectives: fewer semesters, balanced load, fewer prerequisite delays
- [ ] Several alternative plans per student
- [ ] Alternative options for a course
- [ ] Minimum grade requirements (all completed courses are treated as an A today)
- [x] Optionality for taking a certain course by the time one graduates: `StudentProfile.requested_courses`, each optionally due by a plan semester or a credit count (required courses too), scheduled and audited
- [ ] Double/triple/quad degrees: 30 more credits per extra degree (150 for a double degree, 180 for a triple, ...) and at least 18 credits in each major that no other major counts

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
