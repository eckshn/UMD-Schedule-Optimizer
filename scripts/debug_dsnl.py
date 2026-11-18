"""Debug test to understand why DSNL courses aren't being extracted."""

from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.models.schedule import SemesterType
from optimizer.core.optimizer import ScheduleOptimizer


def main():
    # Load course catalogs
    data_dir = Path("sample_data")
    loader = DataLoader(data_dir)
    
    gened_courses = loader.load_courses("GENED")
    
    print(f"Loaded {len(gened_courses)} Gen Ed courses")
    
    # Create minimal requirements with just DSNS and DSNL
    major_reqs = MajorRequirements(
        major_code="TEST",
        major_name="Test",
        department="Test",
        degree_type="BS",
        supporting_courses=[
            Requirement(
                id="gened_dsns",
                type=RequirementType.GEN_ED,
                name="Natural Sciences (DSNS)",
                gen_ed_category="DSNS",
                min_credits=3,
                min_courses=1
            ),
            Requirement(
                id="gened_dsnl",
                type=RequirementType.GEN_ED,
                name="Natural Sciences Lab (DSNL)",
                gen_ed_category="DSNL",
                min_credits=4,
                min_courses=1
            ),
        ],
        min_credits=7,
        min_major_credits=0,
        min_upper_level_credits=0
    )
    
    # Create minimal student
    student = StudentProfile(
        student_id="UID000001",
        name="Test Student",
        primary_major="TEST",
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
    
    # Create optimizer
    optimizer = ScheduleOptimizer(gened_courses)
    
    # Extract required courses
    print("\nExtracting required courses...")
    required_courses = optimizer._get_required_courses(degree_program)
    
    print(f"\nRequired courses extracted: {len(required_courses)}")
    for course_code in required_courses:
        course = gened_courses[course_code]
        print(f"  {course_code:12s} {course.name[:50]:50s} {course.credits} cr - {course.gen_ed_options}")
    
    print(f"\nGen Ed course assignments:")
    for course_code, assigned_categories in optimizer._gen_ed_course_assignments.items():
        print(f"  {course_code}: {assigned_categories}")
    
    # Now try to generate a schedule
    print("\n" + "="*80)
    print("Generating schedule...")
    print("="*80)
    
    schedule = optimizer.optimize_schedule(
        degree_program,
        start_year=2025,
        start_semester=SemesterType.FALL
    )
    
    print(f"\nSchedule has {len(schedule.semesters)} semesters")
    for semester in schedule.semesters:
        if semester.courses:
            print(f"\n{semester.type.value} {semester.year}:")
            for course_code in semester.courses:
                course = gened_courses[course_code]
                print(f"  {course_code:12s} {course.name[:40]:40s} {course.credits} cr - {course.gen_ed_options}")


if __name__ == "__main__":
    main()
