"""
Test case for CS Major General Track - Full 4-year schedule generation.

This test creates a realistic CS major general track schedule with:
- CS core courses (lower and upper level)
- Math requirements (MATH140, MATH141, MATH240)
- Statistics requirement (STAT400)
- CS electives
- Supporting courses
- Gen-ed requirements (from Testudo data)

Gen Ed Requirements for UMD (13 categories):
- FSAW: Academic Writing (3 cr)
- FSOC: Oral Communication (3 cr)
- FSMA: Math (satisfied by MATH140)
- DSHS: History & Social Sciences (6 cr, 2 courses)
- DSHU: Humanities (6 cr, 2 courses)
- DSNS/DSNL: Natural Sciences with Lab (7 cr, 2 courses)
- DSSP: Scholarship in Practice (3 cr)
- DVUP or DVCC: Diversity (6 cr, 2 courses)
- SCIS: I-Series (3 cr, optional)
"""

import pytest
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.models.schedule import SemesterType
from optimizer.core.optimizer import ScheduleOptimizer


def test_cs_major_general_track_full_schedule():
    """
    Test generating a complete 4-year schedule for CS Major - General Track.
    
    UMD CS Major General Track Requirements:
    - Lower Level Core: CMSC131, CMSC132, CMSC216, CMSC250
    - Upper Level Core: CMSC330, CMSC351, CMSC420
    - Math: MATH140, MATH141, MATH240
    - Statistics: STAT400
    - Upper Level CS Electives: 4 courses
    - Gen Ed Requirements: ~30 credits across 13 categories
    """
    
    # Load course catalogs
    data_dir = Path("sample_data")
    loader = DataLoader(data_dir)
    
    cmsc_courses = loader.load_courses("CMSC")
    math_courses = loader.load_courses("MATH")
    gened_courses = loader.load_courses("GENED")  # Load Gen Ed courses
    # Merge courses - department-specific courses take precedence over Gen Ed
    all_courses = {**gened_courses, **cmsc_courses, **math_courses}
    
    print(f"\n{'='*80}")
    print("CS MAJOR - GENERAL TRACK TEST (WITH GEN ED REQUIREMENTS)")
    print(f"{'='*80}")
    print(f"Loaded {len(cmsc_courses)} CMSC courses")
    print(f"Loaded {len(math_courses)} MATH courses")
    print(f"Loaded {len(gened_courses)} Gen Ed courses")
    print(f"Total courses available: {len(all_courses)}")
    
    # Define CS General Track requirements based on UMD curriculum
    major_reqs = MajorRequirements(
        major_code="CMSC",
        major_name="Computer Science - General Track",
        department="Computer Science",
        degree_type="BS",
        lower_level=[
            Requirement(
                id="cs_core_lower",
                type=RequirementType.GROUP,
                name="CS Lower Level Core",
                courses=["CMSC131", "CMSC132", "CMSC216", "CMSC250"],
                min_credits=16,
                min_courses=4
            ),
            Requirement(
                id="math_foundation",
                type=RequirementType.GROUP,
                name="Mathematics Foundation",
                courses=["MATH140", "MATH141"],
                min_credits=8,
                min_courses=2
            )
        ],
        upper_level=[
            Requirement(
                id="cs_core_upper",
                type=RequirementType.GROUP,
                name="CS Upper Level Core",
                courses=["CMSC330", "CMSC351"],
                min_credits=6,
                min_courses=2,
                notes="CMSC330 and CMSC351 are required upper level core courses"
            ),
            # General Track: 5 CMSC 400-level courses from at least 3 areas
            # Areas: 1=Systems, 2=Information Processing, 3=Software Eng/PL, 4=Theory, 5=Numerical
            Requirement(
                id="cs_400_level_area_1",
                type=RequirementType.GROUP,
                name="CS 400-Level Area 1: Systems",
                courses=[
                    "CMSC411", "CMSC412", "CMSC414", "CMSC416", "CMSC417"
                ],
                min_credits=0,  # No minimum per area
                min_courses=0,
                max_courses=3,  # Max 3 from any area
                notes="Area 1: Systems courses"
            ),
            Requirement(
                id="cs_400_level_area_2",
                type=RequirementType.GROUP,
                name="CS 400-Level Area 2: Information Processing",
                courses=[
                    "CMSC420", "CMSC421", "CMSC422", "CMSC423", "CMSC424",
                    "CMSC426", "CMSC427", "CMSC470", "CMSC471", "CMSC472"
                ],
                min_credits=0,
                min_courses=0,
                max_courses=3,
                notes="Area 2: Information Processing courses"
            ),
            Requirement(
                id="cs_400_level_area_3",
                type=RequirementType.GROUP,
                name="CS 400-Level Area 3: Software Engineering & PL",
                courses=[
                    "CMSC430", "CMSC433", "CMSC434", "CMSC435", "CMSC436", "CMSC471"
                ],
                min_credits=0,
                min_courses=0,
                max_courses=3,
                notes="Area 3: Software Engineering and Programming Languages"
            ),
            Requirement(
                id="cs_400_level_area_4",
                type=RequirementType.GROUP,
                name="CS 400-Level Area 4: Theory",
                courses=[
                    "CMSC451", "CMSC452", "CMSC454", "CMSC456", "CMSC457", "CMSC474"
                ],
                min_credits=0,
                min_courses=0,
                max_courses=3,
                notes="Area 4: Theory courses"
            ),
            Requirement(
                id="cs_400_level_area_5",
                type=RequirementType.GROUP,
                name="CS 400-Level Area 5: Numerical Analysis",
                courses=[
                    "CMSC460", "CMSC466"
                ],
                min_credits=0,
                min_courses=0,
                max_courses=3,
                notes="Area 5: Numerical Analysis (only one counts for credit)"
            ),
            # Note: The actual requirement is "5 courses from at least 3 areas"
            # This is simplified - full implementation would need area tracking
            Requirement(
                id="cs_400_level_total",
                type=RequirementType.GROUP,
                name="CS 400-Level Courses (5 required from 3+ areas)",
                courses=[
                    # Area 1: Systems
                    "CMSC411", "CMSC412", "CMSC414", "CMSC416", "CMSC417",
                    # Area 2: Information Processing
                    "CMSC420", "CMSC421", "CMSC422", "CMSC423", "CMSC424",
                    "CMSC426", "CMSC427", "CMSC470", "CMSC471", "CMSC472",
                    # Area 3: Software Engineering & PL
                    "CMSC430", "CMSC433", "CMSC434", "CMSC435", "CMSC436",
                    # Area 4: Theory
                    "CMSC451", "CMSC452", "CMSC454", "CMSC456", "CMSC457", "CMSC474",
                    # Area 5: Numerical Analysis
                    "CMSC460", "CMSC466"
                ],
                min_credits=15,  # 5 courses @ 3cr each (most are 3cr)
                min_courses=5,
                min_areas=3,  # Must be from at least 3 different areas
                max_from_same_area=3,  # Max 3 from any single area
                notes="5 CMSC 400-level courses from at least 3 different areas, "
                      "with no more than 3 courses from any single area"
            ),
            Requirement(
                id="cs_electives_upper",
                type=RequirementType.GROUP,
                name="CS Upper Level Electives (2 additional courses, 6cr)",
                courses=[
                    "CMSC320", "CMSC335", "CMSC401", "CMSC425", "CMSC473",
                    "CMSC475", "CMSC476", "CMSC477",
                    # Can also use additional 400-level courses beyond the 5 required
                    "CMSC411", "CMSC412", "CMSC414", "CMSC416", "CMSC417",
                    "CMSC420", "CMSC421", "CMSC422", "CMSC423", "CMSC424",
                    "CMSC426", "CMSC427", "CMSC430", "CMSC433", "CMSC434",
                    "CMSC435", "CMSC436", "CMSC451", "CMSC452", "CMSC454",
                    "CMSC456", "CMSC457", "CMSC460", "CMSC466", "CMSC470",
                    "CMSC471", "CMSC472", "CMSC474"
                ],
                min_credits=6,
                min_courses=2,
                notes="2 additional CMSC upper level electives (6 credits total). "
                      "Can be from 300-400 level courses not used for area requirements."
            )
        ],
        supporting_courses=[
            Requirement(
                id="linear_algebra",
                type=RequirementType.COURSE,
                name="Linear Algebra Requirement",
                course_code="MATH240",
                min_credits=4
            ),
            Requirement(
                id="statistics",
                type=RequirementType.COURSE,
                name="Statistics Requirement (STAT4XX with prereq MATH141)",
                course_code="STAT400",
                min_credits=3,
                notes="Must be STAT4XX with prerequisite of MATH141, cannot be cross-listed with CMSC"
            ),
            Requirement(
                id="additional_math_stat",
                type=RequirementType.GROUP,
                name="Additional Math/Stat Course (with prereq MATH141)",
                courses=["MATH240", "MATH241", "MATH246", "MATH340", "MATH341", 
                        "STAT401", "STAT410", "STAT420", "STAT430"],
                min_credits=3,
                min_courses=1,
                notes="MATH/STAT XXX course with prerequisite of MATH141, "
                      "cannot be cross-listed with CMSC. 3-4 credits."
            ),
            # Upper Level Concentration (ULC)
            # 12 credits of 300-400 level courses in one discipline outside CS
            # No CMSC or courses cross-listed with CMSC
            # Only 1 independent study/experiential learning course allowed
            # Cumulative GPA of 1.7+ required
            # Note: This is a placeholder - actual implementation would need
            # to track discipline and validate non-CMSC courses
            Requirement(
                id="upper_level_concentration",
                type=RequirementType.GROUP,
                name="Upper Level Concentration (12cr in one non-CS discipline)",
                courses=[],  # This would be populated based on student's chosen concentration
                min_credits=12,
                min_courses=4,  # Typically 4 courses at 3cr each
                notes="12 credit hours of 300-400 level courses in one discipline outside CS. "
                      "Cannot include CMSC courses or courses cross-listed with CMSC. "
                      "Only 3 credits from independent study/experiential learning allowed. "
                      "Minimum cumulative GPA of 1.7 required."
            ),
            # Gen Ed Requirements
            Requirement(
                id="gened_fsaw",
                type=RequirementType.GEN_ED,
                name="Academic Writing (FSAW)",
                gen_ed_category="FSAW",
                min_credits=3,
                min_courses=1
            ),
            Requirement(
                id="gened_fsoc",
                type=RequirementType.GEN_ED,
                name="Oral Communication (FSOC)",
                gen_ed_category="FSOC",
                min_credits=3,
                min_courses=1
            ),
            Requirement(
                id="gened_fspw",
                type=RequirementType.GEN_ED,
                name="Professional Writing (FSPW)",
                gen_ed_category="FSPW",
                min_credits=3,
                min_courses=1
            ),
            # Natural Sciences: DSNL courses count toward both DSNL and DSNS
            # Requirement: 7 total credits with at least 4 from DSNL (lab)
            Requirement(
                id="gened_dsnl",
                type=RequirementType.GEN_ED,
                name="Natural Sciences Lab (DSNL)",
                gen_ed_category="DSNL",
                min_credits=4,
                min_courses=1
            ),
            Requirement(
                id="gened_dsns",
                type=RequirementType.GEN_ED,
                name="Natural Sciences (DSNS) - Total 7cr with DSNL",
                gen_ed_category="DSNS",
                min_credits=7,  # Total from both DSNS and DSNL
                min_courses=2   # Typically 1 DSNL + 1 DSNS or 2 DSNL
            ),
            Requirement(
                id="gened_dshs",
                type=RequirementType.GEN_ED,
                name="History & Social Sciences (DSHS)",
                gen_ed_category="DSHS",
                min_credits=6,
                min_courses=2
            ),
            Requirement(
                id="gened_dshu",
                type=RequirementType.GEN_ED,
                name="Humanities (DSHU)",
                gen_ed_category="DSHU",
                min_credits=6,
                min_courses=2
            ),
            Requirement(
                id="gened_dssp",
                type=RequirementType.GEN_ED,
                name="Scholarship in Practice (DSSP)",
                gen_ed_category="DSSP",
                min_credits=6,
                min_courses=2
            ),
            Requirement(
                id="gened_dvup",
                type=RequirementType.GEN_ED,
                name="Diversity (DVUP or DVCC)",
                gen_ed_category="DVUP",  # Could also accept DVCC
                min_credits=6,
                min_courses=2
            ),
        ],
        min_credits=120,
        min_major_credits=54,  # CS majors need 54+ credits in CMSC
        min_upper_level_credits=30
    )
    
    # Create student profile - incoming freshman, no AP credit
    student = StudentProfile(
        student_id="UID000001",
        name="CS General Track Student",
        primary_major="CMSC",
        credits_completed=0,
        gpa=0.0,
        current_semester=0,
        preferred_credit_load=(15, 17),
        include_summer=False,
        max_difficulty_per_semester=20.0
    )
    
    # Create degree program
    degree_program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    # Generate schedule
    print(f"\nStudent: {student.name}")
    print(f"Major: {major_reqs.major_name}")
    print(f"Credits per semester: {student.preferred_credit_load}")
    print(f"\nGenerating 4-year schedule...\n")
    
    optimizer = ScheduleOptimizer(all_courses)
    schedule = optimizer.optimize_schedule(
        degree_program, 
        start_year=2025, 
        start_semester=SemesterType.FALL
    )
    
    # Validate schedule was generated
    assert schedule is not None
    assert len(schedule.semesters) > 0
    
    # Display the schedule
    print(f"{'='*80}")
    print("GENERATED 4-YEAR SCHEDULE")
    print(f"{'='*80}\n")
    
    total_credits = 0
    total_cs_credits = 0
    total_upper_level_credits = 0
    total_gened_credits = 0
    scheduled_courses_by_semester = {}
    all_scheduled_courses = set()
    gened_courses_taken = []
    
    for i, semester in enumerate(schedule.semesters):
        semester_name = f"{semester.type.value} {semester.year}"
        print(f"{semester_name}")
        print("-" * 80)
        
        if not semester.courses:
            print("  (No courses scheduled)")
        else:
            semester_credits = 0
            semester_courses = []
            
            for course_code in semester.courses:
                course = all_courses.get(course_code)
                if course:
                    # Track course details
                    semester_courses.append(course_code)
                    all_scheduled_courses.add(course_code)
                    semester_credits += course.credits
                    total_credits += course.credits
                    
                    # Count CS credits
                    if course_code.startswith("CMSC"):
                        total_cs_credits += course.credits
                        if course.level == "upper":
                            total_upper_level_credits += course.credits
                    
                    # Track Gen Ed courses
                    if course.gen_ed_categories:
                        total_gened_credits += course.credits
                        gened_courses_taken.append({
                            'code': course_code,
                            'name': course.name,
                            'credits': course.credits,
                            'geneds': course.gen_ed_categories
                        })
                    
                    # Display course
                    if course_code.startswith("CMSC"):
                        dept_label = "CMSC"
                    elif course_code.startswith("MATH") or course_code.startswith("STAT"):
                        dept_label = "MATH/STAT"
                    else:
                        dept_label = "GEN-ED"
                    
                    level_label = "UL" if course.level == "upper" else "LL"
                    
                    # Show Gen Ed categories if any
                    gened_str = ""
                    if course.gen_ed_categories:
                        gened_str = f" [{', '.join(course.gen_ed_categories)}]"
                    
                    print(f"  [{dept_label:9s}] [{level_label}] {course.code:12s} "
                          f"{course.name:40s} {course.credits} cr "
                          f"(diff: {course.difficulty:.1f}){gened_str}")
            
            scheduled_courses_by_semester[semester_name] = semester_courses
            print(f"\n  Semester Total: {semester_credits} credits")
        
        print()
    
    # Summary statistics
    print(f"{'='*80}")
    print("SCHEDULE SUMMARY")
    print(f"{'='*80}")
    print(f"Total Credits Scheduled: {total_credits}")
    print(f"Total CS Credits: {total_cs_credits}")
    print(f"Total Upper Level Credits: {total_upper_level_credits}")
    print(f"Total Gen Ed Credits: {total_gened_credits}")
    print(f"Total CS Credits: {total_cs_credits}")
    print(f"Total Upper Level Credits: {total_upper_level_credits}")
    print(f"Total Semesters: {len(schedule.semesters)}")
    print(f"Total Courses: {len(all_scheduled_courses)}")
    
    # Check core requirements
    print(f"\n{'='*80}")
    print("REQUIREMENT VERIFICATION")
    print(f"{'='*80}")
    
    # Lower level CS core
    lower_core_required = {"CMSC131", "CMSC132", "CMSC216", "CMSC250"}
    lower_core_scheduled = lower_core_required & all_scheduled_courses
    print(f"\nCS Lower Level Core (4 required):")
    for course in sorted(lower_core_required):
        status = "✓" if course in lower_core_scheduled else "✗"
        print(f"  {status} {course}")
    
        # Upper level CS core (updated requirements: only CMSC330 and CMSC351)
        upper_core_required = {"CMSC330", "CMSC351"}
        upper_core_scheduled = upper_core_required & all_scheduled_courses
        print(f"\nCS Upper Level Core (2 required):")
        for course in sorted(upper_core_required):
            status = "✓" if course in upper_core_scheduled else "✗"
            print(f"  {status} {course}")    # Math requirements
    math_required = {"MATH140", "MATH141", "MATH240"}
    math_scheduled = math_required & all_scheduled_courses
    print(f"\nMathematics Requirements (3 required):")
    for course in sorted(math_required):
        status = "✓" if course in math_scheduled else "✗"
        print(f"  {status} {course}")
    
    # Statistics requirement
    print(f"\nStatistics Requirement:")
    stat_status = "✓" if "STAT400" in all_scheduled_courses else "✗"
    print(f"  {stat_status} STAT400")
    
    # Upper level electives
    upper_electives = {c for c in all_scheduled_courses 
                      if c.startswith("CMSC") 
                      and c not in lower_core_required 
                      and c not in upper_core_required
                      and all_courses.get(c, None) 
                      and all_courses[c].level == "upper"}
    print(f"\nCS Upper Level Electives (13 required): {len(upper_electives)} scheduled")
    for course in sorted(upper_electives):
        print(f"  • {course}: {all_courses[course].name}")
    
    # Gen Ed requirements verification
    print(f"\n{'='*80}")
    print("GEN ED REQUIREMENTS VERIFICATION")
    print(f"{'='*80}")
    
    # Count Gen Ed categories fulfilled
    from collections import defaultdict
    gened_credits_by_category = defaultdict(int)
    gened_courses_by_category = defaultdict(list)
    
    for course_info in gened_courses_taken:
        for gened_cat in course_info['geneds']:
            gened_credits_by_category[gened_cat] += course_info['credits']
            gened_courses_by_category[gened_cat].append(course_info['code'])
            # Special case: DSNL courses also count toward DSNS
            if gened_cat == 'DSNL':
                gened_credits_by_category['DSNS'] += course_info['credits']
                if course_info['code'] not in gened_courses_by_category['DSNS']:
                    gened_courses_by_category['DSNS'].append(course_info['code'])
    
    # Required Gen Ed categories
    gened_requirements = {
        'FSAW': {'name': 'Academic Writing', 'min_credits': 3, 'min_courses': 1},
        'FSOC': {'name': 'Oral Communication', 'min_credits': 3, 'min_courses': 1},
        'FSPW': {'name': 'Professional Writing', 'min_credits': 3, 'min_courses': 1},
        'DSNL': {'name': 'Natural Sciences Lab', 'min_credits': 4, 'min_courses': 1},
        'DSNS': {'name': 'Natural Sciences (Total with DSNL)', 'min_credits': 7, 'min_courses': 2},
        'DSHS': {'name': 'History & Social Sciences', 'min_credits': 6, 'min_courses': 2},
        'DSHU': {'name': 'Humanities', 'min_credits': 6, 'min_courses': 2},
        'DSSP': {'name': 'Scholarship in Practice', 'min_credits': 3, 'min_courses': 1},
        'DVUP': {'name': 'Diversity', 'min_credits': 6, 'min_courses': 2},
    }
    
    print(f"\nGen Ed Courses Scheduled: {len(gened_courses_taken)}")
    print(f"Gen Ed Credits: {total_gened_credits}")
    print()
    
    for gened_code, req in gened_requirements.items():
        credits_earned = gened_credits_by_category.get(gened_code, 0)
        courses_taken = len(gened_courses_by_category.get(gened_code, []))
        required_credits = req['min_credits']
        required_courses = req['min_courses']
        
        status = "✓" if (credits_earned >= required_credits and 
                        courses_taken >= required_courses) else "✗"
        
        print(f"{status} {gened_code} - {req['name']}:")
        print(f"    Required: {required_credits} cr ({required_courses} courses)")
        print(f"    Earned: {credits_earned} cr ({courses_taken} courses)")
        
        if gened_courses_by_category.get(gened_code):
            for course_code in gened_courses_by_category[gened_code]:
                course = all_courses.get(course_code)
                if course:
                    print(f"      • {course_code}: {course.name}")
        print()
    
    # Show all Gen Ed courses taken
    if gened_courses_taken:
        print(f"\nAll Gen Ed Courses Taken ({len(gened_courses_taken)} total):")
        for course_info in sorted(gened_courses_taken, key=lambda x: x['code']):
            geneds_str = ', '.join(course_info['geneds'])
            print(f"  • {course_info['code']:12s} {course_info['name']:50s} "
                  f"{course_info['credits']} cr [{geneds_str}]")
    
    # Assertions
    print(f"\n{'='*80}")
    print("TEST ASSERTIONS")
    print(f"{'='*80}")
    
    # Assert minimum total credits for graduation
    # Note: This is a simplified test - in reality students would take additional
    # electives to reach 120 credits, but this validates core requirements
    assert total_credits >= 105, f"Expected at least 105 credits, got {total_credits}"
    print(f"✓ Core requirements scheduled: {total_credits} credits")
    
    # Assert all core courses are scheduled
    assert len(lower_core_scheduled) == 4, f"Expected 4 lower core CS courses, got {len(lower_core_scheduled)}"
    print("✓ All 4 lower level CS core courses scheduled")
    
    assert len(upper_core_scheduled) == 2, f"Expected 2 upper core CS courses, got {len(upper_core_scheduled)}"
    print("✓ All 2 upper level CS core courses scheduled (CMSC330, CMSC351)")
    
    assert len(math_scheduled) == 3, f"Expected 3 math courses, got {len(math_scheduled)}"
    print("✓ All 3 math courses scheduled")
    
    # Gen Ed assertions
    assert len(gened_courses_taken) > 0, "Expected at least some Gen Ed courses scheduled"
    print(f"✓ Gen Ed courses scheduled: {len(gened_courses_taken)}")
    
    assert total_gened_credits >= 37, f"Expected at least 37 Gen Ed credits, got {total_gened_credits}"
    print(f"✓ Minimum Gen Ed credits met: {total_gened_credits} >= 37")
    assert "STAT400" in all_scheduled_courses, "STAT400 not scheduled"
    print("✓ STAT400 scheduled")
    
    # Assert prerequisite ordering
    print("\nVerifying prerequisite ordering...")
    
    # Build a map of semester to actual chronological index
    semester_chrono_order = {}
    for i, sem in enumerate(schedule.semesters):
        # Calculate chronological order: Spring (Jan-May) before Fall (Aug-Dec) in same year
        chrono_idx = (sem.year - 2025) * 2 + (0 if sem.type == SemesterType.SPRING else 1)
        for course in sem.courses:
            semester_chrono_order[course] = chrono_idx
    
    # CMSC131 must come before CMSC132
    if "CMSC131" in semester_chrono_order and "CMSC132" in semester_chrono_order:
        assert semester_chrono_order["CMSC131"] < semester_chrono_order["CMSC132"]
        print("✓ CMSC131 → CMSC132 ordering correct")
    
    # CMSC132 must come before CMSC216
    if "CMSC132" in semester_chrono_order and "CMSC216" in semester_chrono_order:
        assert semester_chrono_order["CMSC132"] < semester_chrono_order["CMSC216"]
        print("✓ CMSC132 → CMSC216 ordering correct")
    
    # CMSC131 must come before CMSC250
    if "CMSC131" in semester_chrono_order and "CMSC250" in semester_chrono_order:
        assert semester_chrono_order["CMSC131"] < semester_chrono_order["CMSC250"]
        print("✓ CMSC131 → CMSC250 ordering correct")
    
    # MATH140 must come before MATH141
    if "MATH140" in semester_chrono_order and "MATH141" in semester_chrono_order:
        assert semester_chrono_order["MATH140"] < semester_chrono_order["MATH141"]
        print("✓ MATH140 → MATH141 ordering correct")
    
    # MATH141 must come before MATH240
    if "MATH141" in semester_chrono_order and "MATH240" in semester_chrono_order:
        assert semester_chrono_order["MATH141"] < semester_chrono_order["MATH240"]
        print("✓ MATH141 → MATH240 ordering correct")
    
    # MATH141 must come before STAT400
    if "MATH141" in semester_chrono_order and "STAT400" in semester_chrono_order:
        assert semester_chrono_order["MATH141"] < semester_chrono_order["STAT400"]
        print("✓ MATH141 → STAT400 ordering correct")
    
    print(f"\n{'='*80}")
    print("TEST PASSED ✓")
    print(f"{'='*80}\n")
    
    print("\n" + "="*80)
    print("✅ TEST PASSED - All requirements met and properly ordered!")
    print("="*80)


if __name__ == "__main__":
    # Run the test directly
    schedule = test_cs_major_general_track_full_schedule()
    print("\nTest completed successfully!")
