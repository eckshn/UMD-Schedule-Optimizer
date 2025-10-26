# Testudo Schedule of Classes Scraper

## Overview

`scrape_testudo.py` scrapes course information from the UMD Testudo Schedule of Classes (SOC) website. This scraper extracts more detailed information than the Academic Catalog scraper, including:

- **Gen Ed categories** (with full names)
- **Current semester offerings** (whether the course is being offered)
- **Number of sections** (how many sections are available)
- **Grading methods** (Regular, Pass-Fail, Audit)
- **Prerequisites and Corequisites**
- **Enrollment restrictions**

## Data Source

- **Website**: https://app.testudo.umd.edu/soc/
- **Default Term**: 202601 (Spring 2026)
- **Format**: HTML pages with structured course data

## Usage

### Scrape a single department
```bash
python scrape_testudo.py CMSC
```

### Scrape multiple departments
```bash
python scrape_testudo.py CMSC MATH STAT PHYS
```

### Scrape all departments from departments.md
```bash
python scrape_testudo.py --all
```

### Specify a different term
```bash
python scrape_testudo.py CMSC --term 202501  # Fall 2025
python scrape_testudo.py CMSC --term 202608  # Fall 2026
```

### Control output format
```bash
python scrape_testudo.py CMSC --format json       # JSON only
python scrape_testudo.py CMSC --format markdown   # Markdown only
python scrape_testudo.py CMSC --format both       # Both (default)
```

### Adjust delay between requests
```bash
python scrape_testudo.py --all --delay 2.0  # 2 seconds between requests
```

## Output

The scraper creates two files per department in the `testudo_courses/` directory:

1. **JSON file** (`department.json`): Machine-readable format with full course data
2. **Markdown file** (`department.md`): Human-readable format for review

### JSON Structure

```json
{
  "department": "CMSC",
  "term_id": "202601",
  "courses": [
    {
      "code": "CMSC131",
      "name": "Object-Oriented Programming I",
      "credits": 4,
      "gen_eds": [],
      "grading_method": "Regular",
      "description": null,
      "prerequisites": [],
      "corequisites": ["MATH140"],
      "restrictions": [],
      "is_offered_this_term": false,
      "num_sections": 0
    }
  ]
}
```

### Gen Ed Information

Gen Ed categories are captured with both code and full name:

```json
{
  "code": "AAAS100",
  "name": "Introduction to African American and Africana Studies",
  "gen_eds": [
    {
      "code": "DSHS",
      "name": "Distributive Studies - History and Social Sciences"
    },
    {
      "code": "DVUP",
      "name": "Diversity - Understanding Plural Societies"
    }
  ]
}
```

## Common Gen Ed Codes

- **DSHS**: Distributive Studies - History and Social Sciences
- **DSHU**: Distributive Studies - Humanities  
- **DSNS**: Distributive Studies - Natural Sciences
- **DSNL**: Distributive Studies - Natural Sciences Lab
- **DSSP**: Distributive Studies - Social Sciences
- **DVUP**: Diversity - Understanding Plural Societies
- **DVCC**: Diversity - Cultural Competence
- **FSAR**: Fundamental Studies - Arts
- **FSAW**: Fundamental Studies - Academic Writing
- **FSMA**: Fundamental Studies - Math
- **FSOC**: Fundamental Studies - Oral Communication
- **SCIS**: Signature Courses - I-Series (Big Question)

## Differences from Academic Catalog Scraper

| Feature | Academic Catalog | Testudo SOC |
|---------|-----------------|-------------|
| **Gen Ed Categories** | ❌ Not available | ✅ Full codes and names |
| **Current Offerings** | ❌ Not available | ✅ Yes/No + section count |
| **Grading Methods** | ❌ Not available | ✅ Regular/P-F/Audit |
| **Course Descriptions** | ✅ Detailed | ⚠️ Basic (less detail) |
| **Historical Data** | ✅ All courses | ⚠️ Only recent courses |
| **Variable Credits** | ✅ Full ranges | ⚠️ Min credits only |

## Use Cases

### For Schedule Optimizer
The Gen Ed information from Testudo is valuable for:
- Automatically categorizing courses by Gen Ed requirements
- Helping students plan Gen Ed completion
- Validating degree requirements with Gen Ed constraints

### For Semester Planning
The offering information helps:
- Determine which courses are available in a given semester
- Identify popular courses (many sections)
- Plan around course availability

## Example: Scrape All Departments

```bash
# Scrape all 195 departments with 1.5 second delay
python scrape_testudo.py --all --delay 1.5 --format both

# Output: testudo_courses/
#   aaas.json, aaas.md
#   aast.json, aast.md
#   ...
#   wmsx.json, wmsx.md
```

## Term ID Format

Term IDs follow the pattern: `YYYYMM`
- `YYYY`: Year
- `MM`: Semester code
  - `01`: Spring
  - `05`: Summer
  - `08`: Fall
  - `12`: Winter

Examples:
- `202501`: Fall 2025
- `202601`: Spring 2026
- `202605`: Summer 2026
- `202608`: Fall 2026

## Notes

- Testudo may not have all historical courses (only recent offerings)
- Some courses may show as "not offered" if they're not available this term
- The Academic Catalog scraper (`scrape_umd_catalog.py`) should be used for comprehensive course descriptions
- Consider using both scrapers for complete course information:
  - **Testudo**: Gen Ed codes, current offerings
  - **Academic Catalog**: Full descriptions, all historical courses
