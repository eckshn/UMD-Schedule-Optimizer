---
name: run-stack
description: How to set up and run this repo's UMD schedule optimizer: install deps with uv, run the pytest suite or a single test, check determinism, run the prototype CLI and example scripts, and run the Testudo/catalog scrapers and GENED.json rebuild. Use when asked to run, test, demo, or verify a change in this project, or to refresh course data.
---

# Running the UMD Schedule Optimizer

Everything is plain Python. There's no server, database or frontend. "The stack" consists of:

1. the `optimizer/` library,
2. the pytest suite in `tests/`,
3. `prototype_cli.py` and the demo scripts in `examples/`, which print a 4-year plan,
4. scrapers in `scrapers/` that refresh course data from UMD's websites.

**Always run commands from the repo root.** Scripts load data from the relative path `sample_data/`. `uv sync` installs the `optimizer` package in editable mode, so scripts in `examples/` and `scripts/` can be run by path.

## 1. Environment

The project is managed by `uv` (`pyproject.toml` + `uv.lock`; `.python-version` asks for 3.13).

```bash
uv sync          # creates .venv (gitignored) and installs deps
```

**If `uv` isn't installed** (`command not found`), don't install it system-wide without asking the user. The machine's python may have no `pip` or `ensurepip`, so the venv route doesn't work either. Instead, download the standalone binary into your scratchpad and keep all of its state there:

```bash
SCRATCH=<your scratchpad dir>
mkdir -p "$SCRATCH/uv" && curl -fsSL https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz | tar xz -C "$SCRATCH/uv"
export UV="$SCRATCH/uv/uv-x86_64-unknown-linux-gnu/uv" \
       UV_CACHE_DIR="$SCRATCH/uvcache" UV_PROJECT_ENVIRONMENT="$SCRATCH/venv" UV_PYTHON_INSTALL_DIR="$SCRATCH/pythons"
"$UV" sync
```

Then use `"$UV" run ...` wherever this skill says `uv run ...`. Shell state doesn't persist between Bash calls, so re-export those variables in every command. Suggest that the user install uv themselves.

## 2. Tests

```bash
uv run pytest -q                                                    # whole suite
uv run pytest -q tests/test_optimizer.py::test_prerequisite_simple  # one test
uv run pytest -q -s tests/test_cs_major_general_track.py            # prints the full CS plan
```

pytest config lives in `pyproject.toml` (`testpaths = ["tests"]`). `scripts/debug_*.py`/`check_*.py` files are scripts, not tests (run with `uv run python scripts/<name>.py`).

**Determinism check:** run this after any change to `optimizer/core/`. Planner output must not depend on hash ordering:

```bash
for s in 0 1 2 3 4; do PYTHONHASHSEED=$s uv run pytest -q 2>&1 | tail -1; done
```

Every line should report the same all-passed count. `tests/test_course_selection.py::test_schedule_is_identical_across_hash_seeds` covers this too.

## 3. Running the planner

```bash
uv run python prototype_cli.py   # main demo: CS General Track student with AP Calc credit
uv run python examples/example_full.py   # CS + MATH + gen-ed example
uv run python examples/example.py        # small hand-built catalog
```

`prototype_cli.py` loads `sample_data/courses/*.json`, `sample_data/majors/CMSC.json` and a sample student, then prints a semester-by-semester plan and its validation result.

**What normal output looks like:** a `Schedule has N validation errors:` warning on stderr (logged by `optimizer.core.optimizer`, with up to 5 `  - ...` lines) is normal. Errors are soft checks such as `Only 14 credits (min 15)` or `Too difficult (20.7 > 20.0)`, and the plan is returned anyway. These indicate a real regression:
- `Prerequisites not met for ...` (the scheduler or validator is broken)
- a traceback
- core courses (CMSC131/132/216/250/330/351, MATH140/141/240, STAT400) missing from the plan

Plans come to about 120–121 credits, including free electives that fill the gap to the major's 120-credit minimum. The last semester is often light (`Only N credits (min 12)`), because the greedy scheduler fills earlier semesters first.

For one-off experiments, put the script in your scratchpad and run it with the repo on the import path:

```bash
PYTHONPATH=. uv run python "$SCRATCH/try.py"
```

Minimal programmatic use:

```python
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.models.student import StudentProfile, StudentDegreeProgram

loader = DataLoader(Path("sample_data"))
program = StudentDegreeProgram(
    student=StudentProfile(student_id="1", name="t", primary_major="CMSC"),
    primary_major=loader.load_major("CMSC"),
    minors=[loader.load_minor("RAS")],          # optional
    gen_ed_requirements=loader.load_gen_eds(),  # university-wide gen-eds
)
print(ScheduleOptimizer(loader.load_catalog()).optimize_schedule(program))
```

## 4. Refreshing course data (network)

The scrapers hit live UMD sites and **overwrite committed files**. Before running them:
- Confirm with the user before scraping many departments.
- Keep the default ≥1s `--delay`.
- When you only want to test a scraper, pass `--output "$SCRATCH/out"` so the tracked data isn't touched.

```bash
# Testudo Schedule of Classes -> data/testudo_courses/{dept}.json/.md (gen-eds, offerings)
uv run python scrapers/scrape_testudo.py CMSC MATH [--term 202601] [--delay 1.0] [--format json|markdown|both]
uv run python scrapers/scrape_testudo.py --all     # ALL ~195 departments from data/departments/departments.md: slow; ask first
./scrapers/check_testudo_progress.sh               # progress of a running --all scrape

# Academic Catalog -> data/scraped_courses/ (full descriptions, no gen-eds)
uv run python scrapers/scrape_umd_catalog.py CMSC  # its --all means only 8 CS-related depts

# Rebuild the gen-ed catalog the optimizer uses from data/testudo_courses/*.json
# WARNING: runs immediately and overwrites the committed GENED.json, which has hand-added
# prerequisites (e.g. ENGL101 on 18 FSPW courses) that rebuilding erases. Ask first, then review `git diff`.
uv run python scrapers/generate_gened.py           # writes sample_data/courses/GENED.json
```

After regenerating `GENED.json`, rerun the test suite. Gen-ed selection depends on that file, so the CS plan's gen-ed courses may change.

## Quick reference

| Goal | Command |
|---|---|
| Install | `uv sync` |
| All tests | `uv run pytest -q` |
| One test | `uv run pytest -q tests/<file>.py::<test>` |
| See a plan | `uv run python prototype_cli.py` |
| Determinism | `PYTHONHASHSEED=<n> uv run pytest -q` for a few `n` |
| Refresh gen-eds | `scrapers/scrape_testudo.py <DEPTS>` then `scrapers/generate_gened.py` |
