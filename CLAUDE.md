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
uv run python examples/example_full.py    # end-to-end demo against sample_data/
uv run python prototype_cli.py            # prototype CLI
```

The `run-stack` skill (`.claude/skills/run-stack/SKILL.md`) has the full run guide: a `uv` fallback when it isn't installed, what normal planner output looks like, and safe scraper usage.

Run everything from the repo root. Several scripts and tests load data with the relative path `Path("sample_data")`. `optimizer` is an installable package (hatchling, see `pyproject.toml`), and `uv sync` installs it in editable mode. That's what lets `examples/*.py` and `scripts/*.py` import it when run by path (`uv run python scripts/check_cycles.py`). pytest only collects tests from `tests/`. `scripts/debug_*.py`, `check_*.py` and `trace_optimizer.py` are ad-hoc scripts, not tests.

Scheduling must stay deterministic. `tests/test_course_selection.py::test_schedule_is_identical_across_hash_seeds` runs the planner under several `PYTHONHASHSEED`s, so never let output depend on `set`/`dict` iteration of unordered data.

## Architecture

### Pipeline (`optimizer/core/optimizer.py` → `ScheduleOptimizer.optimize_schedule`)
1. **Select courses**: `select_courses` → `CourseSelector.select` (`optimizer/core/selection.py`) returns a `Selection`: the chosen `courses`, `by_requirement` (courses per requirement, keyed by index path into `get_all_requirements()` and nested `courses`/`choices`, since `id`s can collide) and the locked `gen_ed_options`. All per-run state lives in a private `_SelectionRun`, so the selector is reentrant. It walks `StudentDegreeProgram.get_all_requirements()` in order (major lower/upper/supporting/concentration, secondary major, minors, gen-eds, then the major's credit minimums).
   - `COURSE` requirements claim their course.
   - `GROUP` and `CHOICE` requirements go through `_pick_from_group`. It picks just enough courses to meet `min_courses`, `min_credits` and `min_areas` (areas come from `Course.areas`; `max_from_same_area` caps any one area). It prefers, in order: courses already credited, courses whose prerequisites are reachable, courses from a new area, then the listed order. A `GROUP` with neither `min_courses` nor `min_credits` takes every listed course.
   - A course claimed by one major requirement can't satisfy another (for example, electives beyond the 400-level picks).
   - A requirement with `exclusive: false` (the CS Upper Level Concentration, which may overlap with a minor) doesn't claim its picks: they go in `shared`, and later GROUP/CHOICE/CATEGORY requirements prefer reusing them (`_free`), claiming them as they do. A non-exclusive CATEGORY prefers courses later requirements list (`listed_after`).
   - `CATEGORY` (`_select_category`) is a rule, not a list: any catalog course passing its filters (`pattern`, `departments`, `exclude_departments`, which also rejects courses cross-listed with those departments, the `min_level`/`max_level` number range, and `has_prerequisite`) counts toward `min_courses`/`min_credits`. The filter is `categories.category_matches`, shared with the audit. It prefers credited (or shared), then reachable, then (non-exclusive only) later-listed, then unrestricted courses, then course code. Picks stay within `max_independent_study_credits` (`categories.within_limits`, shared with the audit; `rules.is_independent_study` goes by course name). With `single_department`, it compares each department's picks and takes the first that meets the minimums, ranked by fewest unreachable picks, then fewest restricted picks, then (non-exclusive only) the most picks a later requirement lists, then the most credited/selected courses already in that department, then name. The CS `statistics` (STAT4xx needing MATH141), `additional_math_stat` (MATH/STAT needing MATH141) and Upper Level Concentration requirements are all CATEGORYs.
   - `CREDIT_HOURS` (`_select_electives`) adds free electives. These requirements are filled after every other requirement, most specific (filtered) first, so upper-level picks also count toward the total. Credits counted so far come from `categories.credit_hours`, shared with the audit, plus `prior_credits` for unfiltered ones. Candidates must be offered, undergraduate (`rules.is_undergraduate`), pass the filters and not already be planned. They're preferred in this order: no restrictions, reachable prerequisites, credits closest to `rules.TYPICAL_COURSE_CREDITS`, departments with the most planned/credited courses, then code. They're listed in `Selection.electives` and don't claim courses.
   - `GEN_ED` (`_select_gen_ed`) first counts credited or already-selected courses whose gen-ed option covers the category. That reuse is how double counting happens, e.g. DS + DV, or DSNL → DSNS. If more is needed, it picks catalog courses in this order: no restrictions, then reachable prerequisites, then credits closest to `min_credits / min_courses`, then course code. The chosen option for each course is locked in a `GenEdLedger`.
2. **Drop completed courses** with `StudentProfile.has_completed`. "Completed" means `credited_courses()`: taken courses, AP *values*, and transfer *keys*.
3. **Order** with `_scheduling_priority`. Courses that start the longest chain of required dependents come first. Ties go to courses offered in fewer terms, then to topological order. Free electives are then moved to the end, so they only fill room left by required courses. `PrerequisiteGraph.topological_sort` breaks its own ties by input order.
4. **Greedy semester assignment** (`_assign_courses_to_semesters`) over 8 Fall/Spring semesters. A course is added when all of these hold:
   - its prerequisites are met by courses from earlier semesters
   - it is offered that term
   - credits stay within `preferred_credit_load` max
   - `rules.py` allows it: at most 3 upper-level (300–499) CMSC courses per semester, and FSPW gen-eds only after 60 cumulative credits
5. **Validate** with `ConstraintValidator.validate_schedule`. Credited courses count toward prerequisites. Errors are only logged as warnings (`logging`, never configured by the library); the schedule is still returned.

**Requirement audit** (`optimizer/core/audit.py`): `audit_requirements(courses, requirements, catalog) -> AuditReport` is the one authority on whether requirements are met, for any list of courses (generated or hand-written). `ScheduleOptimizer.audit(program, schedule=None)` audits the schedule plus credited courses (credited only without a schedule). Each `RequirementResult` gives `satisfied`, the `applied` courses, `credits` and a `reason` when unmet. It follows the selection rules above (equivalents count, GROUP minimums/areas, CATEGORY filters, single department and independent study cap, no double counting across COURSE/GROUP/CHOICE/CATEGORY except that a non-exclusive requirement's courses stay available to later ones, gen-eds reuse courses with option locking) using a deterministic greedy pass whose limits are in the module docstring. Plan courses a later CATEGORY matches count as demanded by it, so earlier requirements leave them for it when they can. `CREDIT_HOURS` sums the credits of every plan course passing the CATEGORY filters (no filters means every course) without claiming them. `ScheduleOptimizer.audit` passes `prior_credits` (`categories.prior_credits`: `credits_completed` minus the credited courses the catalog knows), and those count only toward unfiltered CREDIT_HOURS. `MajorRequirements.credit_requirements()` turns `min_credits` and `min_upper_level_credits` into `total_credits`/`upper_level_credits` requirements, which `get_all_requirements()` appends after the gen-eds. `min_major_credits` isn't checked, because the source material's definition of it (54 "CS credits") matches no count of the plan. The CS plan meets every requirement, at about 121 credits.

`GenEdLedger` (`optimizer/core/gen_eds.py`) is the single implementation of gen-ed option locking, used by both the selector and the audit. Don't reimplement "does this course count toward category X" elsewhere.

UMD policy rules (the upper-level CMSC limit, FSPW at 60 credits, DSNL→DSNS, which course names mean independent study) live in `optimizer/core/rules.py`. The scheduler applies them and `ConstraintValidator` re-checks the cap and the credit minimums, counting `StudentProfile.credits_completed`. Add new policies there rather than in `optimizer.py` or `constraints.py`.

### Catalog and course equivalence
`optimizer/models/catalog.py` `Catalog` is a read-only `Mapping[str, Course]`. Everything that takes a catalog also accepts a plain dict; `ScheduleOptimizer` and `ConstraintValidator` wrap it with `Catalog.of(...)`. Honors and base versions (`XXXX100H` ↔ `XXXX100`) and cross-listed courses (detected by an *identical course name*, indexed once in `__init__`) are treated as the same course:
- `Catalog.equivalents` / `has_equivalent_in`, and `dedupe_equivalents`, which keeps order but prefers the non-honors version
- `StudentProfile.has_completed` has no catalog, so it only handles the honors/base pair (shared `honors_pair` helper)

`Catalog.course_number` (`CMSC498A` → 498), `Catalog.department` (`CMSC498A` → `CMSC`) and `primary_area` (`Course.areas[0]`) are the other lookup helpers. `Catalog.requires(code, prereq)` says whether every prerequisite path of `code` goes through `prereq` (transitively; OR alternatives missing from the catalog are ignored, cycles count as not requiring). Policy built on them, like the 300–499 cap, belongs in `rules.py`.

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
- `load_major`/`load_minor` read `data_dir/majors/{CODE}.json` and `data_dir/minors/{CODE}.json`. Each requirement object's keys map directly onto `Requirement` dataclass fields, and `type` is a `RequirementType` value. Requirements can be nested inside `courses`/`choices`, and `{"code": ...}` is shorthand for a single-course requirement. Only `majors/CMSC.json` and `minors/RAS.json` exist so far. `Requirement.__post_init__` raises `ValueError` if a type's own field is missing (COURSE→`course_code`, CHOICE→`choices`, GROUP→`courses`, which may be `[]`, GEN_ED→`gen_ed_category`, CATEGORY→`min_courses` or `min_credits`, CREDIT_HOURS→`min_credits`).
- Gen-eds are university-wide, not part of a major: `load_gen_eds("UMD")` reads `data_dir/gen_eds/UMD.json` (`{"requirements": [...]}`). Callers pass the result as `StudentDegreeProgram(gen_ed_requirements=...)`, which `get_all_requirements()` puts last, so gen-eds can reuse courses already picked for the major.
- Courses in the RAS minor from departments other than CMSC/MATH (ENME, ENAE, ENEE) aren't in `sample_data/courses/`. The optimizer silently skips requirements whose courses aren't in the catalog.
- `sample_data/courses/` holds the catalog the optimizer actually uses: `CMSC.json`, `MATH.json` and `GENED.json`. `DataLoader.load_catalog()` (alias `load_all_courses()`) assembles them into a `Catalog`: GENED first, then department files in name order overriding its entries. A department entry with no `gen_eds` keeps GENED's `gen_ed_options`/`gen_ed_categories` (that is how MATH140 gets FSAR/FSMA).

### Data acquisition (`scrapers/`)
- `scrape_testudo.py`: scrapes the Testudo Schedule of Classes for a term (default `202601`) into `data/testudo_courses/{dept}.json/.md`. This is the source of `gen_eds`. Usage: `python scrapers/scrape_testudo.py CMSC MATH`, `--all` (department list from `data/departments/departments.md`), `--term`, `--delay`, `--format`. More detail in `scrapers/README.md`.
- `scrape_umd_catalog.py`: scrapes the Academic Catalog into `data/scraped_courses/`. It has fuller descriptions but no gen-ed data.
- `generate_gened.py`: rebuilds `sample_data/courses/GENED.json` from every course in `data/testudo_courses/*.json` that has gen-eds. It overwrites as soon as it runs, and the committed file has hand-added prerequisites (`ENGL101` on 18 FSPW courses) that a rebuild erases, so review `git diff` afterwards.
- Default paths in these scripts are relative to the repo root, so run them from there.

### Reference docs in repo
- `docs/notes.md`: original design notes.
- `docs/history.md`: log of past bug fixes.
- `docs/requirements/`: UMD requirement source material used to write tests (`CS_MAJOR_REQUIREMENTS_SUMMARY.md`, `cs_reqs.txt`, `robotics_minor.txt`, `sample4year.md`, `math.md`).

## Notes
- Besides the courses requirements call for, plans only add the free electives needed to reach the major's `min_credits`. The CS plan gets about 12 credits of extra CMSC courses this way, because the department preference favors the student's biggest department. Unit tests that build a `MajorRequirements` set `min_credits=0` to keep electives out.
- `MajorRequirements.benchmarks` (credit checkpoints for limited-enrollment programs, see `docs/notes.md`) is not checked anywhere yet; nothing populates it. Add it to the audit when a major needs it.
- Schedules sort chronologically with Spring before Fall within a calendar year. Fall *Y* is followed by Spring *Y+1*.
