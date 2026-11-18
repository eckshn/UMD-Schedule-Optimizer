"""Example with CMSC and MATH courses combined."""

from pathlib import Path
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader


def main():
    """Load CMSC and MATH courses and generate a realistic CS schedule."""
    
    data_dir = Path("sample_data")
    loader = DataLoader(data_dir)
    
    # Load courses from both departments
    print("Loading courses...")
    cmsc_courses = loader.load_courses("CMSC")
    math_courses = loader.load_courses("MATH")
    
    # Combine into one catalog
    all_courses = {**cmsc_courses, **math_courses}
    print(f"Loaded {len(cmsc_courses)} CMSC courses and {len(math_courses)} MATH courses")
    print(f"Total catalog: {len(all_courses)} courses\n")
    
    # Create a realistic CS major requirement
    major_reqs = MajorRequirements(
        major_code="CMSC",
        major_name="Computer Science",
        department="Computer Science",
        degree_type="BS",
        lower_level=[
            Requirement(
                id="cs_lower",
                type=RequirementType.GROUP,
                name="CS Lower Level Core",
                courses=["CMSC131", "CMSC132", "CMSC216", "CMSC250"],
                min_credits=16
            ),
            Requirement(
                id="math_lower",
                type=RequirementType.GROUP,
                name="Math Foundation",
                courses=["MATH140", "MATH141"],
                min_credits=8
            )
        ],
        upper_level=[
            Requirement(
                id="cs_upper_core",
                type=RequirementType.GROUP,
                name="CS Upper Level Core",
                courses=["CMSC330", "CMSC351", "CMSC420"],
                min_credits=10
            )
        ],
        supporting_courses=[
            Requirement(
                id="math_support",
                type=RequirementType.GROUP,
                name="Math Supporting Courses",
                courses=["MATH240", "STAT400"],
                min_credits=7
            )
        ],
        min_credits=120,
        min_major_credits=60
    )
    
    # Create student profile - typical incoming freshman
    student = StudentProfile(
        student_id="UID123456",
        name="CS Student",
        primary_major="CMSC",
        credits_completed=0,
        gpa=0.0,
        preferred_credit_load=(15, 17)
    )
    
    # Create degree program
    degree_program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    # Generate schedule
    print("=" * 80)
    print("UMD COMPUTER SCIENCE - 4-YEAR SCHEDULE")
    print("=" * 80)
    print(f"Student: {student.name} ({student.student_id})")
    print(f"Major: {major_reqs.major_name}")
    print(f"Target credits per semester: {student.preferred_credit_load[0]}-{student.preferred_credit_load[1]}")
    print()
    print("Generating optimized schedule...")
    print()
    
    optimizer = ScheduleOptimizer(all_courses)
    schedule = optimizer.optimize_schedule(degree_program, start_year=2025)
    
    # Display schedule
    print("=" * 80)
    print("GENERATED 4-YEAR SCHEDULE")
    print("=" * 80)
    
    total_credits = 0
    for semester in schedule.semesters:
        semester_name = f"{semester.type.value} {semester.year}"
        print(f"\n{semester_name}")
        print("-" * 80)
        
        if not semester.courses:
            print("  (No courses scheduled)")
        else:
            semester_credits = 0
            for course_code in semester.courses:
                course = all_courses.get(course_code)
                if course:
                    dept = "CMSC" if course_code.startswith("CMSC") else "MATH/STAT"
                    prereq_info = ""
                    if course.prerequisites:
                        prereq_count = len(course.prerequisites)
                        prereq_info = f" [{prereq_count} prereq(s)]"
                    
                    print(f"  {course.code:12s} {course.name:45s} {course.credits} cr  ({dept}){prereq_info}")
                    semester_credits += course.credits
                    total_credits += course.credits
            
            print(f"\n  Semester Total: {semester_credits} credits")
    
    print()
    print("=" * 80)
    print(f"TOTAL CREDITS SCHEDULED: {total_credits}")
    print("=" * 80)
    print()
    
    # Show progression summary
    print("COURSE PROGRESSION:")
    print("-" * 80)
    print("Lower-Level CS: CMSC131 → CMSC132 → CMSC216, CMSC250")
    print("Math Sequence: MATH140 → MATH141 → MATH240")
    print("Upper-Level CS: CMSC330, CMSC351, CMSC420 (after core courses)")
    print()


if __name__ == "__main__":
    main()
