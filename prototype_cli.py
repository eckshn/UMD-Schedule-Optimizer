"""Command-line interface for the schedule optimizer."""

import sys
from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.schedule import SemesterType
from optimizer.core.optimizer import ScheduleOptimizer


def main():
    """Main entry point for the CLI."""
    print("=" * 60)
    print("UMD Schedule Optimizer - Prototype")
    print("=" * 60)
    print()
    
    # Setup data loader
    data_dir = Path(__file__).parent / "sample_data"
    loader = DataLoader(data_dir)
    
    # Load courses
    print("Loading course catalog...")
    courses = loader.load_all_courses()
    print(f"Loaded {len(courses)} courses")
    print()
    
    if not courses:
        print("Error: No courses loaded. Please check sample_data/courses/ directory")
        return
    
    # Create sample student
    print("Creating sample student profile...")
    student = StudentProfile(
        student_id="12345",
        name="Sample Student",
        primary_major="CMSC",
        credits_completed=0,
        gpa=0.0,
        current_semester=0,
        completed_courses={},
        ap_credits={
            "AP Calculus AB": "MATH140"  # Sample AP credit
        }
    )
    print(f"  Name: {student.name}")
    print(f"  Major: {student.primary_major}")
    print(f"  AP Credits: {len(student.ap_credits)}")
    print()
    
    # Load major requirements
    print("Loading major requirements...")
    major_reqs = loader.load_major("CMSC")
    
    if not major_reqs:
        print("Warning: Could not load major requirements")
        print("Creating minimal major requirements...")
        from optimizer.models.requirements import MajorRequirements
        major_reqs = MajorRequirements(
            major_code="CMSC",
            major_name="Computer Science"
        )
    
    print(f"  Major: {major_reqs.major_name}")
    print(f"  Min Credits: {major_reqs.min_credits}")
    print()
    
    # Create degree program
    student_program = StudentDegreeProgram(
        student=student,
        primary_major=major_reqs
    )
    
    # Create optimizer
    print("Initializing schedule optimizer...")
    optimizer = ScheduleOptimizer(courses)
    print()
    
    # Generate schedule
    print("Generating optimized 4-year schedule...")
    print("(This may take a moment...)")
    print()
    
    try:
        schedule = optimizer.optimize_schedule(
            student_program,
            start_year=2025,
            start_semester=SemesterType.FALL
        )
        
        # Display schedule
        print("=" * 60)
        print("GENERATED SCHEDULE")
        print("=" * 60)
        print()
        
        for semester in schedule.semesters:
            credits = semester.total_credits(courses)
            difficulty = semester.total_difficulty(courses)
            
            print(f"{semester.type.value} {semester.year} ({credits} credits, difficulty: {difficulty:.1f})")
            print("-" * 60)
            
            if not semester.courses:
                print("  No courses scheduled")
            else:
                for course_code in semester.courses:
                    if course_code in courses:
                        course = courses[course_code]
                        print(f"  {course.code:10s} {course.name:40s} ({course.credits} cr)")
                    else:
                        print(f"  {course_code:10s} (Course not found)")
            print()
        
        # Summary
        total_credits = schedule.total_credits(courses)
        print("=" * 60)
        print(f"Total Credits: {total_credits}")
        print(f"Total Semesters: {len(schedule.semesters)}")
        print("=" * 60)
        print()
        
        # Validate schedule
        print("Validating schedule...")
        is_valid, errors = optimizer.validator.validate_schedule(
            schedule,
            student,
            min_credits=12,
            max_credits=18
        )
        
        if is_valid:
            print("✓ Schedule is valid!")
        else:
            print(f"⚠ Schedule has {len(errors)} issues:")
            for error in errors[:10]:  # Show first 10 errors
                print(f"  - {error}")
        print()
        
    except Exception as e:
        print(f"Error generating schedule: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 60)
    print("Prototype completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
