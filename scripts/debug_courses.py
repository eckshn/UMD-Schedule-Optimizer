from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.models.student import StudentProfile, StudentDegreeProgram
from optimizer.models.requirements import Requirement, RequirementType, MajorRequirements

# Load courses
loader = DataLoader(Path("sample_data"))
cmsc_courses = loader.load_courses("CMSC")
math_courses = loader.load_courses("MATH")
all_courses = {**cmsc_courses, **math_courses}

# Create requirements
major_reqs = MajorRequirements(
    major_code="CMSC",
    major_name="Computer Science",
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
    min_credits=120
)

student = StudentProfile(
    student_id="TEST",
    name="Test",
    primary_major="CMSC"
)

program = StudentDegreeProgram(
    student=student,
    primary_major=major_reqs
)

# Get all required courses
all_reqs = program.get_all_requirements()
print(f"Total requirements: {len(all_reqs)}")

for req in all_reqs:
    print(f"\nRequirement: {req.name} (type: {req.type.value})")
    if req.courses:
        print(f"  Courses: {req.courses}")
        # Check if they're in catalog
        for course_code in req.courses:
            if course_code in all_courses:
                print(f"    ✓ {course_code} in catalog")
            else:
                print(f"    ✗ {course_code} NOT in catalog!")
