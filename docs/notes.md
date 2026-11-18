# UMD Schedule Optimizer - Design Notes

## Project Goal
Build a 4-year plan schedule builder for college that takes into account previous courses/AP credits and generates an optimized schedule.

---

## High-Level Architecture

### 1. Data Models
- **Student Profile**: Previous courses, AP credits, transfer credits, major/minor requirements, interests
- **Course Catalog**: All available courses with metadata (credits, prerequisites, corequisites, frequency offered)
- **Degree Requirements**: Major requirements, minor requirements, gen-eds, electives, credit minimums
- **Course Schedule**: Historical data on when courses are offered (fall/spring/summer, frequency)

### 2. Core Components

#### A. Prerequisites Resolution System
- Build a dependency graph of courses
- Use topological sorting to determine valid course orderings
- Account for prerequisite chains (e.g., Calc I → Calc II → Calc III)
- Handle OR prerequisites (e.g., "CS101 OR CS103")
- Consider corequisites that must be taken simultaneously

#### B. Credit Evaluation Engine
- Parse AP credits and map to course equivalents
- Evaluate transfer credits
- Track satisfied requirements (major, gen-ed, electives)
- Calculate remaining credits needed

#### C. Constraint Satisfaction System

**Hard Constraints:**
- Prerequisites must be satisfied
- Course availability per semester
- Credit load limits (12-18 credits typically)
- Degree requirements must be met
- Cannot take the same course twice

**Soft Constraints (for optimization):**
- Balanced credit distribution across semesters
- Minimize time-to-graduation
- Course difficulty distribution
- Student preferences
- Course ratings/quality

#### D. Schedule Optimization Algorithm

**Approach Options:**

1. **Constraint Programming (CP)**
   - Use CP-SAT solver (like Google OR-Tools)
   - Model as a constraint satisfaction problem
   - Good for finding feasible solutions quickly

2. **Integer Linear Programming (ILP)**
   - Model as an optimization problem with objective function
   - Maximize/minimize specific goals (graduate early, balanced load, etc.)

3. **Genetic Algorithm / Simulated Annealing**
   - Good for large solution spaces
   - Can handle complex objective functions
   - May not guarantee optimal solution but finds good ones

4. **Backtracking with Heuristics**
   - Start with most constrained semesters
   - Use heuristics like "take prerequisites ASAP"
   - Implement intelligent pruning

**Recommended Hybrid Approach:**
```python
def optimize_schedule(student_profile, course_catalog, requirements):
    # Phase 1: Build prerequisite graph
    course_graph = build_prerequisite_graph(course_catalog)
    
    # Phase 2: Determine required courses
    required_courses = get_required_courses(requirements, student_profile)
    
    # Phase 3: Generate valid orderings using topological sort
    valid_orderings = topological_sort_with_constraints(
        course_graph, 
        required_courses,
        student_profile.completed_courses
    )
    
    # Phase 4: Use CP or ILP to assign courses to semesters
    schedule = constraint_solver(
        valid_orderings,
        availability_constraints,
        credit_limits,
        optimization_objectives
    )
    
    # Phase 5: Refinement - add electives, balance load
    final_schedule = refine_schedule(schedule, preferences)
    
    return final_schedule
```

---

## Optimization Objectives

Weight multiple objectives:
```
Objective Function = 
  w1 * minimize(total_semesters) +
  w2 * minimize(credit_variance) +
  w3 * maximize(course_quality_ratings) +
  w4 * minimize(prerequisite_delays) +
  w5 * maximize(interest_alignment) +
  w6 * minimize(difficulty_spikes)
```

---

## Key Features

- **What-If Analysis**: "What if I switch majors after 2nd year?"
- **Multiple Scenario Generation**: Show 2-3 different optimal paths
- **Real-time Validation**: Check if current plan is on track
- **Course Substitution**: Suggest alternatives if a course is full
- **Summer Session Optimization**: Option to include summer courses
- **Double Major/Minor Support**: Handle multiple requirement sets

---

## Technical Stack Recommendations

### Backend
- Python with OR-Tools (constraint programming)
- NetworkX for graph operations
- NumPy/Pandas for data manipulation
- FastAPI or Flask for API

### Frontend
- React with drag-and-drop (react-beautiful-dnd)
- Calendar/timeline visualization (FullCalendar, vis.js)
- Interactive course graph visualization (D3.js or Cytoscape.js)

### Database
- PostgreSQL for structured data
- Graph database (Neo4j) for course relationships (optional)

---

## Prototype Structure

```
umd-schedule-optimizer/
├── optimizer/
│   ├── __init__.py
│   ├── core/
│   │   ├── optimizer.py        # Core algorithm - REUSABLE
│   │   ├── constraints.py      # Constraint definitions - REUSABLE
│   │   └── graph.py           # Prerequisite graph - REUSABLE
│   ├── models/
│   │   ├── student.py         # Data models - TRANSLATES to DB
│   │   ├── course.py          # Data models - TRANSLATES to DB
│   │   └── schedule.py        # Data models - TRANSLATES to DB
│   └── data/
│       └── loader.py          # Data access - REPLACED by ORM
├── tests/                     # REUSABLE
│   └── test_optimizer.py
├── sample_data/               # Becomes seed data
│   ├── courses.json
│   └── requirements.json
└── prototype_cli.py           # REPLACED by API + frontend
```

---

## Prototype → Production Translation

### What Translates Well ✅
1. **Core Algorithm Logic (95% reusable)**
   - Constraint solving code
   - Graph algorithms (prerequisites, dependencies)
   - Optimization functions
   - Business logic rules

2. **Data Models (90% reusable)**
   - Course structures
   - Student profiles
   - Requirement definitions
   - Can directly become database schemas + API models

3. **Validation Logic (100% reusable)**
   - Prerequisite checking
   - Credit calculation
   - Requirement validation

### What Needs Rewriting ❌
1. **User Interface (100% new)** - CLI/script → Web frontend
2. **Data Storage (70% new design)** - Python dictionaries → Database
3. **API Layer (100% new, but straightforward)** - Function calls → REST/GraphQL

### Effort Breakdown
| Component | Prototype Effort | Production Effort | Reusability |
|-----------|-----------------|-------------------|-------------|
| Core Algorithm | 40 hours | 10 hours | 90% |
| Data Models | 10 hours | 15 hours | 80% |
| API Layer | 0 hours | 20 hours | 0% (new) |
| Frontend | 5 hours (CLI) | 60 hours | 0% (new) |
| Auth/Security | 0 hours | 20 hours | 0% (new) |
| Deployment | 1 hour | 10 hours | 0% (new) |
| **Total** | **~56 hours** | **~135 hours** | **~40% code reuse** |

---

## Prototype Development Guidelines

### DO:
- ✅ Separate concerns (algorithm vs data vs UI)
- ✅ Use type hints (`typing` module)
- ✅ Write unit tests for core logic
- ✅ Use dataclasses or Pydantic models
- ✅ Structure as a package, not a single script
- ✅ Document algorithm decisions

### DON'T:
- ❌ Don't worry about auth/permissions yet
- ❌ Don't optimize for scale (okay to be slow)
- ❌ Don't build a fancy UI
- ❌ Don't worry about deployment

---

## Challenges to Address

- **Data Quality**: Keeping course catalog and prerequisites up-to-date
- **Course Availability Uncertainty**: Courses may not be offered as expected
- **Computational Complexity**: NP-hard problem, need good heuristics
- **User Experience**: Making complex optimization understandable
- **Flexibility**: Students may change plans, fail courses, or take leaves

---

## UMD General Education Requirements

### Fundamental Studies (15 credits)
1. **Academic Writing (AW)** - 3 credits (e.g., ENGL101)
2. **Professional Writing (PW)** - 3 credits (e.g., ENGL393)
3. **Oral Communication (OC)** - 3 credits
4. **Math (MA)** - 4 credits (e.g., MATH140)
5. **Analytic Reasoning (AR)** - 4 credits (e.g., MATH140)

*Note: Math and Analytic Reasoning often satisfied by same course*

### Distributive Studies (25 credits)
6. **Natural Science Lab (NL)** - 4 credits
7. **Natural Sciences (NS)** - 3 credits
8. **History/Social Sciences (HS)** - 3 credits (first)
9. **History/Social Sciences (HS)** - 3 credits (second)
10. **Humanities (HU)** - 3 credits (first)
11. **Humanities (HU)** - 3 credits (second)
12. **Scholarship in Practice (SP)** - 3 credits
13. **Scholarship in Practice (SP) non-major** - 3 credits

### I-Series (6 credits)
14. **I-Series (IS)** - 3 credits (first)
15. **I-Series (IS)** - 3 credits (second)

*Note: I-Series courses normally double count with Distributive Studies*

### Diversity Requirements (6 credits)
16. **Understanding Plural Society (UP)** - 3 credits
17. **Understanding Plural Society (UP) OR Cultural Competency (CC)** - 3 credits

*Note: Diversity requirements may also fulfill a Distributive Studies category*

---

**Total Gen Ed Credits: ~36 credits** (with overlap/double counting allowed)

**Double Counting Rules:**
- I-Series courses typically also count as Distributive Studies
- Diversity requirements may also count as Distributive Studies
- MA and AR often satisfied by the same math course

---

## Major Requirements Data Structure

### Hierarchical Requirement System

Represent requirements using a flexible, composable structure that handles:
- Multiple majors/minors
- Course alternatives (OR logic)
- Groupings with constraints (pick X from Y)
- Cross-listing and course equivalencies
- Double counting rules

### Proposed Data Schema

```python
from dataclasses import dataclass
from typing import List, Optional, Dict, Union
from enum import Enum

class RequirementType(Enum):
    COURSE = "course"                    # Single specific course
    CHOICE = "choice"                    # Pick one from list
    GROUP = "group"                      # Pick X courses from list
    CATEGORY = "category"                # Courses from a category/area
    CREDIT_HOURS = "credit_hours"        # Minimum credit hours
    
class DoubleCountRule(Enum):
    ALLOWED = "allowed"                  # Can count for both majors
    PRIMARY_ONLY = "primary_only"        # Only counts for primary major
    NOT_ALLOWED = "not_allowed"          # Cannot double count
    LIMITED = "limited"                  # Limited double counting (e.g., max 3 courses)

@dataclass
class Course:
    """Individual course representation"""
    code: str                            # e.g., "CMSC131"
    name: str
    credits: int
    prerequisites: List[Union[str, List[str]]]  # List or nested lists for OR logic
    corequisites: List[str]
    areas: List[str]                     # e.g., ["Systems", "Theory"]
    offered: List[str]                   # ["Fall", "Spring", "Summer"]
    difficulty: Optional[float]
    double_count_rule: DoubleCountRule = DoubleCountRule.ALLOWED

@dataclass
class Requirement:
    """Flexible requirement node"""
    id: str
    name: str
    type: RequirementType
    
    # For COURSE type
    course_code: Optional[str] = None
    
    # For CHOICE type (pick 1 from list)
    choices: Optional[List[Union[str, 'Requirement']]] = None
    
    # For GROUP type (pick X from Y)
    courses: Optional[List[Union[str, 'Requirement']]] = None
    min_courses: Optional[int] = None
    max_courses: Optional[int] = None
    min_credits: Optional[int] = None
    
    # For CATEGORY type
    category: Optional[str] = None       # e.g., "Area 1: Systems"
    
    # Constraints
    min_grade: Optional[str] = None      # e.g., "C-"
    max_from_same_area: Optional[int] = None
    min_areas: Optional[int] = None      # e.g., "3 different areas"
    
    # Double counting
    allows_double_count: bool = True
    double_count_limit: Optional[int] = None

@dataclass
class MajorRequirements:
    """Complete major requirement specification"""
    major_code: str                      # e.g., "CMSC"
    major_name: str                      # e.g., "Computer Science"
    
    # Core requirements organized by type
    lower_level: List[Requirement]
    upper_level: List[Requirement]
    supporting_courses: List[Requirement]  # e.g., Math/STAT requirements
    concentration: Optional[Requirement]   # Upper level concentration
    
    # Benchmarks (for LEP programs)
    benchmarks: Optional[Dict[int, List[Requirement]]] = None  # credits -> requirements
    
    # Overall constraints
    min_credits: int = 120
    min_major_credits: int = 0
    min_upper_level_credits: int = 0
    min_gpa: float = 2.0
    min_major_gpa: float = 2.0
    
    # Double major rules
    double_count_rules: Dict[str, DoubleCountRule] = None  # major_code -> rule

@dataclass
class StudentDegreeProgram:
    """Student's degree program (can have multiple majors/minors)"""
    primary_major: MajorRequirements
    secondary_major: Optional[MajorRequirements] = None
    minors: List[MajorRequirements] = None
    
    gen_ed_requirements: List[Requirement] = None
    
    completed_courses: List[str] = None
    ap_credits: Dict[str, str] = None    # AP test -> course equivalency
    transfer_credits: Dict[str, str] = None
```

### Example: CS Major Requirements

```python
# Lower level math requirements
math_requirements = Requirement(
    id="cs_math_lower",
    name="Lower Level Math",
    type=RequirementType.GROUP,
    courses=[
        Requirement(
            id="calc1", 
            name="Calculus I",
            type=RequirementType.COURSE,
            course_code="MATH140"
        ),
        Requirement(
            id="calc2",
            name="Calculus II", 
            type=RequirementType.COURSE,
            course_code="MATH141"
        ),
        Requirement(
            id="stat",
            name="Statistics with MATH141 prereq",
            type=RequirementType.CATEGORY,
            category="STAT4XX",
            min_courses=1
        ),
        Requirement(
            id="math_elective",
            name="Math/Stat with MATH141 prereq",
            type=RequirementType.CATEGORY,
            category="MATH/STAT",
            min_courses=1,
            min_credits=3
        )
    ],
    min_courses=4
)

# Upper level with area constraints
upper_level_cs = Requirement(
    id="cs_upper",
    name="Upper Level CS Courses",
    type=RequirementType.GROUP,
    courses=[
        # Area 1: Systems
        Requirement(
            id="area1",
            name="Area 1: Systems",
            type=RequirementType.CATEGORY,
            category="Area1_Systems",
            choices=["CMSC411", "CMSC412", "CMSC414", "CMSC416", "CMSC417"]
        ),
        # Area 2: Information Processing
        # ... similar for other areas
    ],
    min_courses=5,
    min_areas=3,              # Must take from at least 3 areas
    max_from_same_area=3      # No more than 3 from same area
)

# Upper level concentration (outside CS)
concentration = Requirement(
    id="upper_concentration",
    name="Upper Level Concentration",
    type=RequirementType.GROUP,
    min_credits=12,
    min_courses=4,
    category="non_cmsc_upper",
    min_gpa=1.7
)

# Complete CS major
cs_major = MajorRequirements(
    major_code="CMSC",
    major_name="Computer Science",
    lower_level=[
        math_requirements,
        # CS lower level courses...
    ],
    upper_level=[upper_level_cs],
    concentration=concentration,
    benchmarks={
        45: [  # 45 credit benchmark
            Requirement(id="bench45_cmsc131", type=RequirementType.COURSE, 
                       course_code="CMSC131", min_grade="C-"),
            Requirement(id="bench45_cmsc132", type=RequirementType.COURSE,
                       course_code="CMSC132", min_grade="C-"),
            Requirement(id="bench45_math140", type=RequirementType.COURSE,
                       course_code="MATH140", min_grade="C-"),
        ],
        75: [  # 75 credit benchmark
            # ...
        ]
    },
    min_credits=120,
    min_major_gpa=2.0
)
```

### Double Major Optimization Strategy

#### 1. **Course Overlap Detection**

```python
class DoubleMajorOptimizer:
    def find_overlapping_courses(self, major1: MajorRequirements, 
                                 major2: MajorRequirements) -> Dict[str, List[str]]:
        """
        Identify courses that can satisfy requirements in both majors
        
        Returns:
            {
                'direct_overlap': ['MATH140', 'STAT400'],  # Same course in both
                'category_overlap': ['CMSC4XX'],            # Can satisfy category in both
                'concentration_option': ['ECON courses']    # One major's reqs = other's concentration
            }
        """
        overlaps = {
            'direct_overlap': [],
            'category_overlap': [],
            'concentration_option': [],
            'gen_ed_overlap': []
        }
        
        # Check if courses appear in both requirement sets
        # Check if major2's required courses can satisfy major1's concentration
        # Check if courses can double count with gen eds
        
        return overlaps
    
    def calculate_total_credits_needed(self, major1: MajorRequirements,
                                      major2: MajorRequirements,
                                      gen_eds: List[Requirement]) -> int:
        """
        Calculate minimum credits accounting for overlaps
        """
        major1_courses = self.get_all_required_courses(major1)
        major2_courses = self.get_all_required_courses(major2)
        
        # Apply double counting rules
        overlaps = self.find_overlapping_courses(major1, major2)
        
        # Calculate net credits considering overlaps
        total = len(set(major1_courses + major2_courses))
        
        # Factor in gen ed overlaps
        # ...
        
        return total
```

#### 2. **Optimization Objective for Double Major**

```python
def optimize_double_major_schedule(student: StudentDegreeProgram):
    """
    Optimize schedule prioritizing:
    1. Courses that satisfy both majors
    2. Prerequisite chains that enable both paths
    3. Balanced progression in both majors
    4. Meeting both sets of benchmarks
    """
    
    objective_function = (
        w1 * maximize(course_overlap) +
        w2 * minimize(total_semesters) +
        w3 * balance(credits_per_major_per_semester) +
        w4 * minimize(delayed_prerequisites) +
        w5 * maximize(benchmark_satisfaction_rate)
    )
    
    constraints = [
        # Standard constraints
        prerequisites_satisfied,
        credit_limits,
        course_availability,
        
        # Double major specific
        both_majors_completed_by_graduation,
        benchmark_requirements_met_for_both,
        double_count_limits_respected,
        min_credits_per_major,
        concentration_requirements_for_both
    ]
```

#### 3. **Double Counting Rules Implementation**

```python
class DoubleMajorValidator:
    def validate_double_counting(self, course: str, 
                                 major1: str, 
                                 major2: str) -> Dict[str, bool]:
        """
        Check if a course can count toward both majors
        
        Examples:
        - MATH courses can usually count for both CMSC and MATH major
        - A CS student with INFOSCI cannot use CMSC courses in concentration
        - Some universities limit total overlap to 3-4 courses
        """
        rules = {
            'counts_for_major1': True,
            'counts_for_major2': True,
            'counts_for_both': False,
            'reason': ''
        }
        
        # Check cross-listing rules
        # Check department restrictions
        # Check credit limits
        
        return rules
    
    def calculate_effective_credits(self, courses: List[str],
                                   major1: str,
                                   major2: str) -> Dict[str, int]:
        """
        Calculate how many credits count toward each major
        accounting for double counting limits
        """
        return {
            'major1_credits': 0,
            'major2_credits': 0,
            'shared_credits': 0,
            'total_unique_credits': 0
        }
```

### File Structure for Major Requirements

```
data/
├── majors/
│   ├── CMSC.json          # Computer Science
│   ├── MATH.json          # Mathematics  
│   ├── ECON.json          # Economics
│   └── ...
├── gen_eds/
│   └── umd_gen_ed.json    # General education requirements
├── courses/
│   ├── CMSC.json          # All CS courses with metadata
│   ├── MATH.json
│   └── ...
└── double_major_rules/
    ├── CMSC_MATH.json     # Specific rules for CS+Math double major
    ├── CMSC_INFOSCI.json  # CS cannot use CMSC in concentration for INFOSCI
    └── default.json       # Default double major rules
```

### Example Major JSON File

```json
{
  "major_code": "CMSC",
  "major_name": "Computer Science",
  "department": "Computer Science",
  "degree_type": "BS",
  "min_credits": 120,
  
  "requirements": {
    "lower_level_cs": {
      "type": "group",
      "name": "Lower Level CS Courses",
      "courses": [
        {"code": "CMSC131", "credits": 4, "min_grade": "C-"},
        {"code": "CMSC132", "credits": 4, "min_grade": "C-"},
        {"code": "CMSC216", "credits": 4, "min_grade": "C-"},
        {"code": "CMSC250", "credits": 4, "min_grade": "C-"},
        {"code": "CMSC330", "credits": 3, "min_grade": "C-"},
        {"code": "CMSC351", "credits": 3, "min_grade": "C-"}
      ],
      "all_required": true
    },
    
    "math_requirements": {
      "type": "group",
      "name": "Math Requirements",
      "courses": [
        {"code": "MATH140", "credits": 4},
        {"code": "MATH141", "credits": 4},
        {
          "type": "category",
          "name": "Statistics",
          "pattern": "STAT4[0-9]{2}",
          "prerequisites": ["MATH141"],
          "min_courses": 1,
          "credits": 3
        },
        {
          "type": "choice",
          "name": "Math/Stat Elective",
          "options": ["MATH/STAT courses with MATH141 prereq"],
          "min_credits": 3
        }
      ]
    },
    
    "upper_level_cs": {
      "type": "group",
      "name": "Upper Level CS",
      "min_courses": 5,
      "min_areas": 3,
      "max_per_area": 3,
      "areas": {
        "Area1_Systems": ["CMSC411", "CMSC412", "CMSC414", "CMSC416", "CMSC417"],
        "Area2_InfoProcessing": ["CMSC420", "CMSC421", "CMSC422", "CMSC423", "CMSC424"],
        "Area3_SoftwareEng": ["CMSC430", "CMSC433", "CMSC434", "CMSC435", "CMSC436"],
        "Area4_Theory": ["CMSC451", "CMSC452", "CMSC454", "CMSC456", "CMSC457"],
        "Area5_NumericalAnalysis": ["CMSC460", "CMSC466"]
      }
    },
    
    "cs_electives": {
      "type": "credit_hours",
      "name": "CS Electives",
      "min_credits": 6,
      "category": "CMSC3XX or CMSC4XX"
    },
    
    "upper_level_concentration": {
      "type": "group",
      "name": "Upper Level Concentration",
      "min_credits": 12,
      "min_courses": 4,
      "constraints": {
        "level": "300-400",
        "exclude_departments": ["CMSC"],
        "same_discipline": true,
        "min_gpa": 1.7
      }
    }
  },
  
  "benchmarks": {
    "45": {
      "name": "45 Credit Benchmark",
      "courses": [
        {"code": "CMSC131", "min_grade": "C-"},
        {"code": "CMSC132", "min_grade": "C-"},
        {"code": "MATH140", "min_grade": "C-"}
      ],
      "min_gpa": 2.0
    },
    "75": {
      "name": "75 Credit Benchmark",
      "courses": [
        {"code": "CMSC330", "min_grade": "C-"},
        {"code": "CMSC351", "min_grade": "C-"},
        {"code": "STAT4XX", "min_grade": "C-"}
      ],
      "min_gpa": 2.0
    }
  },
  
  "double_major_rules": {
    "default": {
      "allow_double_counting": true,
      "max_overlap_courses": null,
      "concentration_restrictions": []
    },
    "INFOSCI": {
      "allow_double_counting": true,
      "max_overlap_courses": null,
      "concentration_restrictions": ["Cannot use CMSC courses in concentration"]
    }
  }
}
```

### Handling Minors

Minors are similar to majors but with key differences:
1. **Eligibility Requirements**: Must be checked BEFORE allowing declaration
2. **Timing Constraints**: Some require minimum semesters remaining
3. **Restricted Access**: Often limited to specific majors
4. **Sequential Prerequisites**: Core courses often in fixed sequence
5. **Smaller Credit Requirements**: Typically 18-22 credits vs 40+ for majors

#### Extended Data Schema for Minors

```python
@dataclass
class EligibilityRequirement:
    """Requirements to declare/enter a minor"""
    
    # Academic standing
    min_credits_completed: Optional[int] = None      # e.g., 30 for sophomore standing
    min_gpa: Optional[float] = None                  # e.g., 3.0
    min_semesters_remaining: Optional[int] = None    # e.g., 4 semesters left
    
    # Major restrictions
    allowed_majors: Optional[List[str]] = None       # e.g., ["CMSC", "ENME", "ENAE", "ENEE"]
    excluded_majors: Optional[List[str]] = None
    
    # Prerequisite courses
    prerequisite_courses: Optional[List[Union[str, List[str]]]] = None  # OR logic supported
    
    # Additional requirements
    requires_permission: bool = False
    application_required: bool = False
    competitive_admission: bool = False
    
    def check_eligibility(self, student: StudentProfile) -> Tuple[bool, List[str]]:
        """
        Check if student meets eligibility requirements
        
        Returns:
            (is_eligible, list_of_reasons_if_not)
        """
        reasons = []
        
        if self.min_credits_completed and student.credits < self.min_credits_completed:
            reasons.append(f"Need {self.min_credits_completed} credits (have {student.credits})")
        
        if self.min_gpa and student.gpa < self.min_gpa:
            reasons.append(f"Need {self.min_gpa} GPA (have {student.gpa})")
        
        if self.allowed_majors and student.major not in self.allowed_majors:
            reasons.append(f"Major {student.major} not eligible (allowed: {', '.join(self.allowed_majors)})")
        
        if self.min_semesters_remaining:
            remaining = student.calculate_semesters_remaining()
            if remaining < self.min_semesters_remaining:
                reasons.append(f"Need {self.min_semesters_remaining} semesters remaining (have {remaining})")
        
        # Check prerequisite courses
        if self.prerequisite_courses:
            missing = self._check_prerequisites(student.completed_courses, self.prerequisite_courses)
            if missing:
                reasons.append(f"Missing prerequisites: {', '.join(missing)}")
        
        return (len(reasons) == 0, reasons)

@dataclass
class MinorRequirements:
    """Complete minor requirement specification"""
    minor_code: str                          # e.g., "RAS"
    minor_name: str                          # e.g., "Robotics and Autonomous Systems"
    department: str
    
    # Eligibility (checked BEFORE declaration)
    eligibility: EligibilityRequirement
    
    # Core requirements
    core_courses: List[Requirement]          # Required courses in sequence
    supporting_courses: List[Requirement]    # e.g., Math requirements
    electives: List[Requirement]             # Choose X from Y
    
    # Constraints
    min_credits: int                         # e.g., 21-22
    min_gpa: float = 2.0
    min_grade: str = "C-"
    
    # Completion rules
    must_complete_with_major: bool = True    # Cannot be standalone
    max_overlap_with_major: Optional[int] = None  # Some minors limit overlap
    
    # Course sequence/timing
    course_sequence: Optional[List[List[str]]] = None  # [[Year1Fall], [Year1Spring], ...]
    fixed_schedule: bool = False             # If courses only offered in specific semesters
    
    # Restrictions
    restricted_enrollment: bool = True       # Limited to declared minor students
    requires_permission_per_course: bool = False

@dataclass
class StudentProfile:
    """Extended student profile with minor support"""
    # ... existing fields ...
    
    primary_major: str
    declared_minors: List[str] = None
    pending_minors: List[str] = None         # Applied but not yet declared
    
    def can_declare_minor(self, minor: MinorRequirements) -> Tuple[bool, List[str]]:
        """Check if student can declare this minor"""
        return minor.eligibility.check_eligibility(self)
    
    def calculate_semesters_remaining(self) -> int:
        """Calculate how many semesters until graduation"""
        credits_needed = 120 - self.credits_completed
        avg_credits_per_semester = 15
        return math.ceil(credits_needed / avg_credits_per_semester)
```

#### Example: Robotics Minor (RAS)

```python
# Eligibility requirements
ras_eligibility = EligibilityRequirement(
    min_credits_completed=30,                # Sophomore standing
    min_gpa=3.0,
    min_semesters_remaining=4,
    allowed_majors=["CMSC", "ENME", "ENAE", "ENEE"],  # Aerospace, ECE, MechE, CS
    prerequisite_courses=[
        ["MATH246", "ENES221"],              # Diff Eq OR Dynamics
        ["CMSC131", "ENME202", "ENAE202", "ENEE150"]  # Programming requirement
    ]
)

# Core courses (must be taken in sequence)
ras_core = [
    Requirement(
        id="ras_core_1",
        name="ENME480 - Introduction to Robotics",
        type=RequirementType.COURSE,
        course_code="ENME480",
        min_grade="C-",
        offered=["Fall"],                    # Only Fall
        prerequisites=[["MATH246", "ENES221"], ["CMSC131", "ENME202", "ENAE202", "ENEE150"]],
        restricted_enrollment=True,
        notes="Year 1 Fall - First course in sequence"
    ),
    Requirement(
        id="ras_core_2",
        name="ENAE450 - Robotics Programming",
        type=RequirementType.COURSE,
        course_code="ENAE450",
        min_grade="C-",
        offered=["Spring"],                  # Only Spring
        prerequisites=["ENME480"],
        restricted_enrollment=True,
        notes="Year 1 Spring - Second in sequence"
    ),
    Requirement(
        id="ras_core_3",
        name="ENEE467 - Robotics Project Laboratory",
        type=RequirementType.COURSE,
        course_code="ENEE467",
        min_grade="C-",
        offered=["Fall"],                    # Only Fall
        prerequisites=["ENAE450"],
        restricted_enrollment=True,
        notes="Year 2 Fall - Third in sequence"
    ),
    Requirement(
        id="ras_core_4",
        name="CMSC477 - Robotics Perception and Planning",
        type=RequirementType.COURSE,
        course_code="CMSC477",
        min_grade="C-",
        offered=["Spring"],                  # Only Spring
        prerequisites=["ENEE467", ["MATH240", "MATH461"]],
        restricted_enrollment=True,
        notes="Year 2 Spring - Final core course. Requires Linear Algebra"
    )
]

# Supporting math requirement
ras_math = Requirement(
    id="ras_math",
    name="Linear Algebra Requirement",
    type=RequirementType.CHOICE,
    choices=["MATH240", "MATH461", "MATH340", "MATH341", "ENEE290"],
    min_courses=1,
    notes="Must be completed BEFORE CMSC477"
)

# Technical electives
ras_electives = Requirement(
    id="ras_electives",
    name="Technical Electives",
    type=RequirementType.GROUP,
    min_courses=2,
    min_credits=6,
    choices=[
        "ENES467", "ENME400", "ENME410", "ENME461", "ENME413", "ENME444",
        "ENME476", "ENME441", "ENME467", "ENME435",
        "CMSC421", "CMSC422", "CMSC426", "CMSC427", "CMSC451", "CMSC498E",
        "ENEE440", "ENEE460", "ENEE461", "ENEE425", "ENEE408I",
        "ENAE380", "ENAE441", "ENAE403", "ENAE432", "ENAE488O"
    ]
)

# Complete minor definition
robotics_minor = MinorRequirements(
    minor_code="RAS",
    minor_name="Robotics and Autonomous Systems",
    department="Multi-department",
    eligibility=ras_eligibility,
    core_courses=ras_core,
    supporting_courses=[ras_math],
    electives=[ras_electives],
    min_credits=21,  # 12 core + 3-4 math + 6 electives
    min_gpa=2.0,
    min_grade="C-",
    must_complete_with_major=True,
    restricted_enrollment=True,
    fixed_schedule=True,  # Core courses in strict sequence
    course_sequence=[
        ["ENME480"],                         # Year 1 Fall
        ["ENAE450"],                         # Year 1 Spring
        ["ENEE467"],                         # Year 2 Fall
        ["CMSC477"]                          # Year 2 Spring
    ]
)
```

#### Minor Optimization Strategy

```python
class MinorOptimizer:
    def check_minor_feasibility(self, student: StudentProfile, 
                               minor: MinorRequirements) -> Dict:
        """
        Check if student can feasibly complete the minor
        
        Returns:
            {
                'eligible': bool,
                'eligibility_issues': List[str],
                'can_complete_on_time': bool,
                'semesters_needed': int,
                'conflicts_with_major': List[str],
                'recommended_start_semester': str
            }
        """
        result = {
            'eligible': False,
            'eligibility_issues': [],
            'can_complete_on_time': False,
            'semesters_needed': 0,
            'conflicts_with_major': [],
            'recommended_start_semester': None
        }
        
        # Check eligibility
        eligible, reasons = student.can_declare_minor(minor)
        result['eligible'] = eligible
        result['eligibility_issues'] = reasons
        
        if not eligible:
            return result
        
        # Calculate semesters needed for sequence
        if minor.fixed_schedule:
            result['semesters_needed'] = len(minor.course_sequence)
        
        # Check if enough semesters remaining
        semesters_remaining = student.calculate_semesters_remaining()
        result['can_complete_on_time'] = semesters_remaining >= result['semesters_needed']
        
        # Find optimal start semester
        result['recommended_start_semester'] = self._find_optimal_start(
            student, minor
        )
        
        return result
    
    def optimize_with_minor(self, student: StudentProfile,
                           major: MajorRequirements,
                           minor: MinorRequirements) -> Schedule:
        """
        Optimize schedule including both major and minor
        
        Priority:
        1. Check minor eligibility first
        2. Place fixed-sequence minor courses in correct semesters
        3. Fill around minor courses with major requirements
        4. Identify courses that count for both (if allowed)
        5. Balance credit load
        """
        
        # Check feasibility
        feasibility = self.check_minor_feasibility(student, minor)
        if not feasibility['can_complete_on_time']:
            raise InfeasibleScheduleError("Cannot complete minor in time")
        
        schedule = Schedule()
        
        # Block out minor core courses first (they have fixed schedule)
        if minor.fixed_schedule:
            start_semester = self._determine_start_semester(student, minor)
            for i, semester_courses in enumerate(minor.course_sequence):
                semester_index = start_semester + i
                for course in semester_courses:
                    schedule.add_course(semester_index, course, priority="FIXED")
        
        # Add major requirements around minor
        self._fill_major_requirements(schedule, major, student)
        
        # Add minor electives where they fit best
        self._add_minor_electives(schedule, minor)
        
        # Check for overlap opportunities
        overlaps = self._find_major_minor_overlaps(major, minor)
        if overlaps:
            schedule = self._optimize_overlaps(schedule, overlaps)
        
        return schedule
    
    def _find_major_minor_overlaps(self, major: MajorRequirements,
                                   minor: MinorRequirements) -> List[str]:
        """
        Find courses that can count toward both major and minor
        
        Examples:
        - CS major's upper level concentration can be fulfilled by robotics minor courses
        - Math requirements might overlap
        - Some electives might count for both
        """
        overlaps = []
        
        # Check if minor courses can satisfy major's concentration
        if major.concentration:
            minor_courses = self._get_all_minor_courses(minor)
            for course in minor_courses:
                if self._can_count_for_concentration(course, major.concentration):
                    overlaps.append(course)
        
        # Check supporting courses (e.g., Math requirements)
        # ...
        
        return overlaps
```

#### Example Minor JSON File

```json
{
  "minor_code": "RAS",
  "minor_name": "Robotics and Autonomous Systems",
  "department": "Multi-department (CMSC/ENME/ENAE/ENEE)",
  "min_credits": 21,
  "min_gpa": 2.0,
  "min_grade": "C-",
  
  "eligibility": {
    "min_credits_completed": 30,
    "min_gpa": 3.0,
    "min_semesters_remaining": 4,
    "allowed_majors": ["CMSC", "ENME", "ENAE", "ENEE"],
    "prerequisite_courses": {
      "math": ["MATH246", "ENES221"],
      "programming": ["CMSC131", "ENME202", "ENAE202", "ENEE150"]
    },
    "application_required": true,
    "competitive_admission": false
  },
  
  "core_courses": [
    {
      "code": "ENME480",
      "name": "Introduction to Robotics",
      "credits": 3,
      "min_grade": "C-",
      "offered": ["Fall"],
      "prerequisites": {
        "or": [
          ["MATH246", "ENES221"],
          ["CMSC131", "ENME202", "ENAE202", "ENEE150"]
        ]
      },
      "restricted_enrollment": true,
      "sequence_position": 1,
      "typical_semester": "Year 1 Fall"
    },
    {
      "code": "ENAE450",
      "name": "Robotics Programming",
      "credits": 3,
      "min_grade": "C-",
      "offered": ["Spring"],
      "prerequisites": ["ENME480"],
      "restricted_enrollment": true,
      "sequence_position": 2,
      "typical_semester": "Year 1 Spring"
    },
    {
      "code": "ENEE467",
      "name": "Robotics Project Laboratory",
      "credits": 3,
      "min_grade": "C-",
      "offered": ["Fall"],
      "prerequisites": ["ENAE450"],
      "restricted_enrollment": true,
      "sequence_position": 3,
      "typical_semester": "Year 2 Fall"
    },
    {
      "code": "CMSC477",
      "name": "Robotics Perception and Planning",
      "credits": 3,
      "min_grade": "C-",
      "offered": ["Spring"],
      "prerequisites": ["ENEE467", ["MATH240", "MATH461"]],
      "restricted_enrollment": true,
      "sequence_position": 4,
      "typical_semester": "Year 2 Spring"
    }
  ],
  
  "supporting_courses": {
    "linear_algebra": {
      "type": "choice",
      "name": "Linear Algebra Requirement",
      "min_courses": 1,
      "options": ["MATH240", "MATH461", "MATH340", "MATH341", "ENEE290"],
      "timing": "Must complete before CMSC477",
      "credits": "3-4"
    }
  },
  
  "electives": {
    "type": "group",
    "name": "Technical Electives",
    "min_courses": 2,
    "min_credits": 6,
    "options": [
      "ENES467", "ENME400", "ENME410", "ENME461", "ENME413", "ENME444",
      "ENME476", "ENME441", "ENME467", "ENME435",
      "CMSC421", "CMSC422", "CMSC426", "CMSC427", "CMSC451", "CMSC498E",
      "ENEE440", "ENEE460", "ENEE461", "ENEE425", "ENEE408I",
      "ENAE380", "ENAE441", "ENAE403", "ENAE432", "ENAE488O"
    ]
  },
  
  "completion_rules": {
    "must_complete_with_major": true,
    "max_overlap_with_major": null,
    "fixed_schedule": true,
    "total_duration": "2 years (4 semesters)"
  },
  
  "notes": [
    "Core courses must be taken in sequence",
    "Restricted to declared minor students only",
    "Linear algebra must be completed before CMSC477",
    "All core courses offered only once per year"
  ]
}
```

#### User Interface Considerations for Minors

```python
class MinorManagementUI:
    def show_minor_eligibility_check(self, student: StudentProfile) -> Dict:
        """
        Show student which minors they're eligible for and which they're close to
        
        Returns:
            {
                'eligible_now': [list of minors],
                'eligible_next_semester': [list of minors],
                'ineligible': [list with reasons]
            }
        """
        pass
    
    def show_minor_timeline(self, student: StudentProfile, 
                           minor: MinorRequirements) -> Dict:
        """
        Show when student can start and must complete minor
        
        Visual timeline showing:
        - Current semester
        - When eligibility requirements will be met
        - Fixed course sequence
        - Latest possible start date
        - Completion date
        """
        pass
    
    def show_overlap_opportunities(self, major: MajorRequirements,
                                   minor: MinorRequirements) -> List[str]:
        """
        Highlight courses that can count for both major and minor
        
        e.g., "Taking CMSC421 and CMSC422 from the robotics minor 
              can fulfill your CS upper level concentration requirement!"
        """
        pass
```

### Key Minor-Specific Features

1. **Eligibility Checker**: Run before allowing minor declaration
2. **Feasibility Calculator**: Determine if student has enough time
3. **Sequence Planner**: Handle fixed course sequences
4. **Conflict Detector**: Identify scheduling conflicts between major and minor
5. **Overlap Optimizer**: Maximize courses that count for both
6. **Timeline Visualizer**: Show when to start and complete the minor

## Additional Ideas & Future Considerations

_Add new ideas and modifications below as they come up..._

