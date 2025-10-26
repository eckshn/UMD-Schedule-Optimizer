from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements
from optimizer.core.optimizer import ScheduleOptimizer

# Load courses
loader = DataLoader(Path("sample_data"))
all_courses = {**loader.load_courses("CMSC"), **loader.load_courses("MATH")}

# Create requirements
major_reqs = MajorRequirements(
    major_code="CMSC",
    major_name="Computer Science",
    lower_level=[
        Requirement(
            id="cs_lower",
            type=RequirementType.GROUP,
            name="CS Lower",
            courses=["CMSC131", "CMSC132"],
            min_credits=8
        ),
        Requirement(
            id="math_lower",
            type=RequirementType.GROUP,
            name="Math Lower",
            courses=["MATH140", "MATH141"],
            min_credits=8
        )
    ],
    min_credits=120
)

student = StudentProfile(student_id="TEST", name="Test", primary_major="CMSC")
program = StudentDegreeProgram(student=student, primary_major=major_reqs)

# Create optimizer and get required courses
optimizer = ScheduleOptimizer(all_courses)
required_courses = optimizer._get_required_courses(program)

print(f"Required courses ({len(required_courses)}):")
for course in sorted(required_courses):
    if course in all_courses:
        print(f"  {course}: {all_courses[course].name}")
    else:
        print(f"  {course}: NOT IN CATALOG")
