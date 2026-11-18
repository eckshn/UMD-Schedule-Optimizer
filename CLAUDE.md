# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Generates a 4-year course plan for University of Maryland students. It takes completed courses, AP credits, transfer credits and degree requirements into account. The `optimizer/` package is the library. `prototype_cli.py` at the root is the closest thing to an entry point; `main.py` is a stub. Other top-level directories: `examples/` (demo scripts), `scripts/` (ad-hoc debug helpers), `scrapers/` (data acquisition), `data/` (raw scraper output, department lists, scrape logs) and `docs/` (notes and requirement source material).

## Commands

The project uses `uv` (`pyproject.toml`, `uv.lock`, Python 3.13 from `.python-version`). Dependencies: `networkx`, `pytest`, and `requests`/`beautifulsoup4` (scrapers only).

```bash
uv sync                                   # install deps
uv run pytest                             # all tests
uv run pytest tests/test_optimizer.py::test_prerequisite_simple   # single test
uv run pytest -s tests/test_cs_major_general_track.py            # prints the generated schedule
uv run python -m examples.example_full    # end-to-end demo against sample_data/
uv run python prototype_cli.py            # prototype CLI
```

The `run-stack` skill (`.claude/skills/run-stack/SKILL.md`) has the full run guide: a `uv` fallback when it isn't installed, what normal planner output looks like, and safe scraper usage.

Run everything from the repo root. Several scripts and tests load data with the relative path `Path("sample_data")`. The package isn't installed: pytest finds it through `pythonpath = ["."]` in `pyproject.toml`, and only collects tests from `tests/`. Scripts in `examples/` and `scripts/` import `optimizer` from the root, so run them as modules (`uv run python -m scripts.check_cycles`); `python scripts/check_cycles.py` fails with `ModuleNotFoundError`. `scripts/debug_*.py`, `check_*.py` and `trace_optimizer.py` are ad-hoc scripts, not tests.

Scheduling must stay deterministic. `tests/test_course_selection.py::test_schedule_is_identical_across_hash_seeds` runs the planner under several `PYTHONHASHSEED`s, so never let output depend on `set`/`dict` iteration of unordered data.

## Architecture

### Pipeline (`optimizer/core/optimizer.py` → `ScheduleOptimizer.optimize_schedule`)
1. **Select courses**: `_get_required_courses` → `_select_for_requirement` walks `StudentDegreeProgram.get_all_requirements()` in order (major lower/upper/supporting/concentration, secondary major, minors, gen-eds).
   - `COURSE` requirements claim their course.
   - `GROUP` and `CHOICE` requirements go through `_pick_from_group`. It picks just enough courses to meet `min_courses`, `min_credits` and `min_areas` (areas come from `Course.areas`; `max_from_same_area` caps any one area). It prefers, in order: courses already credited, courses whose prerequisites are reachable, courses from a new area, then the listed order. A `GROUP` with neither `min_courses` nor `min_credits` takes every listed course.
   - A course claimed by one major requirement can't satisfy another (for example, electives beyond the 400-level picks).
   - `GEN_ED` (`_select_gen_ed`) first counts credited or already-selected courses whose gen-ed option covers the category. That reuse is how double counting happens, e.g. DS + DV, or DSNL → DSNS. If more is needed, it picks catalog courses in this order: no restrictions, then reachable prerequisites, then credits closest to `min_credits / min_courses`, then course code. The chosen option for each course is locked in `_gen_ed_course_assignments`.
2. **Drop completed courses** with `StudentProfile.has_completed`. "Completed" means `credited_courses()`: taken courses, AP *values*, and transfer *keys*.
3. **Order** with `_scheduling_priority`. Courses that start the longest chain of required dependents come first. Ties go to courses offered in fewer terms, then to topological order. `PrerequisiteGraph.topological_sort` breaks its own ties by input order.
4. **Greedy semester assignment** (`_assign_courses_to_semesters`) over 8 Fall/Spring semesters. A course is added when all of these hold:
   - its prerequisites are met by courses from earlier semesters
   - it is offered that term
   - credits stay within `preferred_credit_load` max
   - the semester has at most 3 upper-level (300–499) CMSC courses
   - for FSPW gen-ed courses, the student has at least 60 cumulative credits
5. **Validate** with `ConstraintValidator.validate_schedule`. Credited courses count toward prerequisites. Errors are only printed as warnings; the schedule is still returned.

Hard-coded UMD rules (the upper-level CMSC limit, FSPW at 60 credits, DSNL→DSNS) are duplicated in both `optimizer.py` and `constraints.py`. Keep the two in sync.

### Course equivalence
Honors and base versions (`XXXX100H` ↔ `XXXX100`) and cross-listed courses (detected by an *identical course name*) are treated as the same course. Three places implement this:
- `ScheduleOptimizer._get_course_equivalents`
- `_deduplicate_equivalent_courses`, which prefers the non-honors version
- `StudentProfile.has_completed`, which only handles the honors/base pair

Name matching uses an index (`_codes_by_name`) built in `__init__`.

### Gen-ed data model
`Course.gen_ed_options` is a list of alternative option groups. For example, `[['DSHS'], ['DSHU','DVUP']]` means a student counts the course *either* as DSHS *or* as DSHU+DVUP, not all three. `gen_ed_categories` is a flattened legacy field. Use `Course.get_gen_ed_option_for_category` rather than reading `gen_ed_categories`.

### Prerequisites
`PrerequisiteCondition` is a tree:
- `COURSE`: *every* listed course is required, each meeting `min_grade` if one is set
- `OR`: any course in `courses`
- `AND`: all of the nested `conditions`

When validating, the optimizer treats every completed course as grade "A". The graph adds an edge for *every* course in an OR, so topological ordering is conservative.

### Data and loading
- `optimizer/data/loader.py` `DataLoader(data_dir)` reads `data_dir/courses/{DEPT}.json`, each shaped as `{"courses": [...]}`.
- Prerequisites can be plain strings (Testudo format) or `{type: course|or|and, ...}` dicts.
- `load_major`/`load_minor` read `data_dir/majors/{CODE}.json` and `data_dir/minors/{CODE}.json`. Each requirement object's keys map directly onto `Requirement` dataclass fields, and `type` is a `RequirementType` value. Requirements can be nested inside `courses`/`choices`, and `{"code": ...}` is shorthand for a single-course requirement. Only `majors/CMSC.json` and `minors/RAS.json` exist so far.
- `majors/CMSC.json` was generated from the requirements built in `tests/test_cs_major_general_track.py`. It includes the gen-ed requirements under `supporting_courses`; if you change one of the two, update the other.
- Courses in the RAS minor from departments other than CMSC/MATH (ENME, ENAE, ENEE) aren't in `sample_data/courses/`. The optimizer silently skips requirements whose courses aren't in the catalog.
- `sample_data/courses/` holds the catalog the optimizer actually uses: `CMSC.json`, `MATH.json` and `GENED.json`. Department files override GENED entries, both in `load_all_courses()` (which loads GENED first) and in tests that merge as `{**gened, **cmsc, **math}`.

### Data acquisition (`scrapers/`)
- `scrape_testudo.py`: scrapes the Testudo Schedule of Classes for a term (default `202601`) into `data/testudo_courses/{dept}.json/.md`. This is the source of `gen_eds`. Usage: `python scrapers/scrape_testudo.py CMSC MATH`, `--all` (department list from `data/departments/departments.md`), `--term`, `--delay`, `--format`. More detail in `scrapers/README.md`.
- `scrape_umd_catalog.py`: scrapes the Academic Catalog into `data/scraped_courses/`. It has fuller descriptions but no gen-ed data.
- `generate_gened.py`: rebuilds `sample_data/courses/GENED.json` from every course in `data/testudo_courses/*.json` that has gen-eds.
- Default paths in these scripts are relative to the repo root, so run them from there.

### Reference docs in repo
- `docs/notes.md`: original design notes.
- `docs/history.md`: log of past bug fixes.
- `docs/requirements/`: UMD requirement source material used to write tests (`CS_MAJOR_REQUIREMENTS_SUMMARY.md`, `cs_reqs.txt`, `robotics_minor.txt`, `sample4year.md`, `math.md`).

## Notes
- Plans contain only courses that requirements call for; no free electives are added. The CS plan comes to about 97 credits, short of 120, partly because the Upper Level Concentration requirement lists no courses.
- Schedules sort chronologically with Spring before Fall within a calendar year. Fall *Y* is followed by Spring *Y+1*.
