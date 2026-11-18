"""Simple example demonstrating the schedule optimizer."""

from pathlib import Path
from optimizer.models.course import Course, PrerequisiteCondition, PrerequisiteType
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.core.optimizer import ScheduleOptimizer
from optimizer.data.loader import DataLoader


def create_simple_example():
    """Create a simple example with a few courses."""
    
    # Create some basic courses
    courses = {
        "CMSC131": Course(
            code="CMSC131",
            name="Object-Oriented Programming I",
            credits=4,
            description="Introduction to programming in Java",
            areas=["major"],
            difficulty=2,
            offered=["Fall", "Spring"]
        ),
        "CMSC132": Course(
            code="CMSC132",
            name="Object-Oriented Programming II",
            credits=4,
            description="Advanced object-oriented programming",
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["CMSC131"],
                    min_grade="C-"
                )
            ],
            areas=["major"],
            difficulty=3,
            offered=["Fall", "Spring"]
        ),
        "CMSC216": Course(
            code="CMSC216",
            name="Introduction to Computer Systems",
            credits=4,
            description="C programming and computer systems",
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["CMSC132"],
                    min_grade="C-"
                )
            ],
            areas=["major"],
            difficulty=4,
            offered=["Fall", "Spring"]
        ),
        "CMSC250": Course(
            code="CMSC250",
            name="Discrete Structures",
            credits=4,
            description="Logic, sets, and proofs",
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["CMSC131"],
                    min_grade="C-"
                )
            ],
            areas=["major"],
            difficulty=4,
            offered=["Fall", "Spring"]
        ),
        "MATH140": Course(
            code="MATH140",
            name="Calculus I",
            credits=4,
            description="Differential calculus",
            areas=["gen_ed", "MA"],
            difficulty=3,
            offered=["Fall", "Spring", "Summer"]
        ),
        "ENGL101": Course(
            code="ENGL101",
            name="Academic Writing",
            credits=3,
            description="Writing course",
            areas=["gen_ed", "AW"],
            difficulty=2,
            offered=["Fall", "Spring"]
        ),
        "MATH141": Course(
            code="MATH141",
            name="Calculus II",
            credits=4,
            description="Integral calculus",
            prerequisites=[
                PrerequisiteCondition(
                    type=PrerequisiteType.COURSE,
                    courses=["MATH140"],
                    min_grade="C-"
                )
            ],
            areas=["gen_ed", "MA"],
            difficulty=3.5,
            offered=["Fall", "Spring"]
        ),
        "HIST100": Course(
            code="HIST100",
            name="Introduction to History",
            credits=3,
            description="Historical methods",
            areas=["gen_ed", "HU"],
            difficulty=2,
            offered=["Fall", "Spring"]
        ),
        "PHYS161": Course(
            code="PHYS161",
            name="General Physics I",
            credits=4,
            description="Mechanics and thermodynamics",
            areas=["gen_ed", "NS"],
            difficulty=3.5,
            offered=["Fall", "Spring"]
        ),
    }
    
    # Create a simple major requirement
    major_reqs = MajorRequirements(
        major_code="CMSC",
        major_name="Computer Science",
        department="Computer Science",
        degree_type="BS",
        lower_level=[
            Requirement(
                id="core_lower",
                type=RequirementType.GROUP,
                name="Core Lower Level",
                courses=["CMSC131", "CMSC132", "MATH140", "MATH141"],
                min_credits=16
            )
        ],
        upper_level=[
            Requirement(
                id="core_upper",
                type=RequirementType.GROUP,
                name="Core Upper Level",
                courses=["CMSC216", "CMSC250"],
                min_credits=8
            )
        ],
        supporting_courses=[
            Requirement(
                id="supporting",
                type=RequirementType.GROUP,
                name="Supporting Courses",
                courses=["PHYS161", "ENGL101", "HIST100"],
                min_credits=10
            )
        ],
        min_credits=120,
        min_major_credits=60
    )
    
    # Create a student profile
    student = StudentProfile(
        student_id="12345",
        name="Test Student",
        primary_major="CMSC",
        credits_completed=0,
        gpa=0.0
    )
    
    # Create degree program
    degree_program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs,
        gen_ed_requirements=[]
    )
    
    # Initialize optimizer
    optimizer = ScheduleOptimizer(courses)
    
    # Generate schedule
    print("=" * 70)
    print("UMD SCHEDULE OPTIMIZER - SIMPLE EXAMPLE")
    print("=" * 70)
    print()
    print(f"Student: {student.name} ({student.student_id})")
    print(f"Major: Computer Science")
    print()
    print("Generating schedule...")
    print()
    
    schedule = optimizer.optimize_schedule(degree_program, start_year=2025)
    
    # Display schedule
    if schedule:
        print("=" * 70)
        print("GENERATED SCHEDULE")
        print("=" * 70)
        print()
        
        for semester in schedule.semesters:
            semester_name = f"{semester.type.value} {semester.year}"
            print(f"\n{semester_name}")
            print("-" * 50)
            
            if not semester.courses:
                print("  (No courses scheduled)")
            else:
                total_credits = 0
                for course_code in semester.courses:
                    course = courses.get(course_code)
                    if course:
                        print(f"  {course.code:12s} {course.name:40s} ({course.credits} cr)")
                        total_credits += course.credits
                
                print(f"\n  Total Credits: {total_credits}")
        
        print()
        print("=" * 70)
        print(f"Total Credits Scheduled: {schedule.total_credits(courses)}")
        print("=" * 70)
    else:
        print("Failed to generate schedule!")
    
    return schedule


def load_and_optimize_from_json():
    """Load courses from JSON and optimize."""
    print("\n\n")
    print("=" * 70)
    print("LOADING FROM JSON DATA")
    print("=" * 70)
    
    data_dir = Path("sample_data")
    
    if not data_dir.exists():
        print("\nSample data directory not found!")
        print("Please create sample_data/courses/CMSC.json first.")
        return
    
    loader = DataLoader(data_dir)
    
    # Load courses from CMSC department
    try:
        courses = loader.load_courses("CMSC")
        print(f"\nLoaded {len(courses)} CMSC courses")
        
        # Print first few courses
        print("\nSample courses:")
        for i, (code, course) in enumerate(list(courses.items())[:5]):
            prereq_str = f" (prereqs: {len(course.prerequisites)})" if course.prerequisites else ""
            print(f"  - {code}: {course.name} ({course.credits} credits){prereq_str}")
    except Exception as e:
        print(f"\nError loading courses: {e}")
    
    print("\nTo run full optimization with JSON data, create major/minor JSON files")
    print("and implement the full prototype_cli.py logic.")


if __name__ == "__main__":
    # Run simple example
    schedule = create_simple_example()
    
    # Try loading from JSON
    load_and_optimize_from_json()
