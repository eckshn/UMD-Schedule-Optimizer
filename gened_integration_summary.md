# Gen Ed Integration Summary

## Overview
Successfully integrated Gen Ed requirements from Testudo scraping data into the CS Major General Track test.

## Changes Made

### 1. Created GENED.json Course Catalog
- **Location**: `sample_data/GENED.json`
- **Content**: 617 Gen Ed courses from all departments
- **Categories**: 13 Gen Ed categories (FSAW, FSOC, DSHS, DSHU, DSSP, DVUP, etc.)

### 2. Updated RequirementType Enum
- **File**: `optimizer/models/requirements.py`
- **Change**: Added `GEN_ED = "gen_ed"` to RequirementType enum
- **Change**: Added `gen_ed_category` field to Requirement class

### 3. Enhanced Test File
- **File**: `tests/test_cs_major_general_track.py`
- **Added**: Gen Ed requirements to major requirements
  - FSAW (Academic Writing): 3 cr, 1 course
  - FSOC (Oral Communication): 3 cr, 1 course
  - DSHS (History & Social Sciences): 6 cr, 2 courses
  - DSHU (Humanities): 6 cr, 2 courses
  - DSSP (Scholarship in Practice): 3 cr, 1 course
  - DVUP (Diversity): 6 cr, 2 courses
- **Added**: Gen Ed tracking in schedule display
- **Added**: Gen Ed verification section
- **Added**: Gen Ed assertions

## Gen Ed Requirements for UMD

### Required Categories (from Testudo data):
1. **FSAW** - Fundamental Studies: Academic Writing (3 cr)
2. **FSOC** - Fundamental Studies: Oral Communication (3 cr)
3. **FSMA** - Fundamental Studies: Math (satisfied by MATH140)
4. **DSHS** - Distributive Studies: History & Social Sciences (6 cr, 2 courses)
5. **DSHU** - Distributive Studies: Humanities (6 cr, 2 courses)
6. **DSNS/DSNL** - Distributive Studies: Natural Sciences + Lab (satisfied by major)
7. **DSSP** - Distributive Studies: Scholarship in Practice (3 cr)
8. **DVUP or DVCC** - Diversity (6 cr, 2 courses)
9. **SCIS** - I-Series/Signature Courses (3 cr, optional)

### Total Gen Ed Credits: ~30 credits

## Available Gen Ed Courses by Category

From the scraped Testudo data:

- **DSHS**: 159 courses (History, Economics, Psychology, Political Science, etc.)
- **DSHU**: 156 courses (Philosophy, Literature, Arts, Music, etc.)
- **DSSP**: 195 courses (Research, Internships, Projects)
- **DVUP**: 130 courses (Diversity and Understanding Plural Societies)
- **SCIS**: 115 courses (I-Series Big Question courses)
- **DVCC**: 34 courses (Cultural Competency)
- **DSNS**: 38 courses (Natural Sciences)
- **DSNL**: 28 courses (Natural Science Labs)
- **FSPW**: 18 courses (Professional Writing)
- **FSAR**: 18 courses (Analytic Reasoning)
- **FSOC**: 10 courses (Oral Communication)
- **FSMA**: 8 courses (Math)
- **FSAW**: 4 courses (Academic Writing)

## Test Enhancements

The updated test now:
1. Loads 617 Gen Ed courses from GENED.json
2. Includes 6 Gen Ed requirements in the major requirements
3. Tracks Gen Ed courses separately in schedule output
4. Displays Gen Ed categories with each course (e.g., `[FSAW]`, `[DSHS, DVUP]`)
5. Verifies Gen Ed completion with detailed breakdown
6. Asserts minimum Gen Ed credits (21+)

## Example Gen Ed Courses

### FSAW (Academic Writing)
- ENGL101: Academic Writing (3 cr)

### FSOC (Oral Communication)
- COMM107: Oral Communication: Principles and Practices (3 cr)

### DSHS (History & Social Sciences)
- HIST111: The Medieval World (3 cr) [DSHS, DVUP]
- ECON200: Principles of Microeconomics (3 cr) [DSHS]
- PSYC100: Introduction to Psychology (3 cr) [DSHS, DSNS]

### DSHU (Humanities)
- PHIL100: Introduction to Philosophy (3 cr) [DSHU]
- ENGL234: African-American Literature and Culture (3 cr) [DSHU, DVUP]

### DVUP (Diversity)
- AAAS100: Introduction to African American and Africana Studies (3 cr) [DSHS, DVUP]

### DSSP (Scholarship in Practice)
- Various research, internship, and project courses across departments

## Next Steps

1. **Test the implementation**:
   ```bash
   pytest tests/test_cs_major_general_track.py -v -s
   ```

2. **Verify Gen Ed scheduling** in the optimizer logic

3. **Add Gen Ed conflict checking** (e.g., some courses count for multiple categories)

4. **Implement double-counting rules** (e.g., can one course satisfy multiple Gen Eds?)

5. **Create Gen Ed-specific optimizer** to maximize efficiency (courses that satisfy multiple requirements)

## Notes

- Math requirement (FSMA) is automatically satisfied by MATH140 (required for CS major)
- Natural Science requirement (DSNS/DSNL) is typically satisfied by CS/Physics courses
- Some Gen Ed courses satisfy multiple categories (e.g., HIST111 counts for both DSHS and DVUP)
- Diversity requirement can be satisfied by either DVUP or DVCC courses
- I-Series (SCIS) is optional but recommended for well-rounded education
