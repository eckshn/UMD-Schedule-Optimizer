from pathlib import Path
from optimizer.data.loader import DataLoader

# Load MATH courses
loader = DataLoader(Path("sample_data"))
math_courses = loader.load_courses("MATH")

print(f"Loaded {len(math_courses)} MATH courses\n")

# Show calculus sequence
print("=== Calculus Sequence ===")
calc_courses = ["MATH115", "MATH140", "MATH141", "MATH240", "MATH241", "MATH246"]
for code in calc_courses:
    if code in math_courses:
        course = math_courses[code]
        prereq_str = ""
        if course.prerequisites:
            prereq_codes = []
            for prereq in course.prerequisites:
                if prereq.type.value == "course":
                    prereq_codes.extend(prereq.courses)
                elif prereq.type.value == "or":
                    prereq_codes.append(f"({' or '.join(prereq.courses)})")
            if prereq_codes:
                prereq_str = f" [prereq: {', '.join(prereq_codes)}]"
        print(f"  {code}: {course.name} ({course.credits} cr){prereq_str}")

# Show upper-level math courses
print("\n=== Upper-Level Math Courses ===")
upper_level = [c for c in math_courses.values() if c.level == "upper"]
print(f"Total upper-level courses: {len(upper_level)}")
for course in sorted(upper_level, key=lambda x: x.code)[:10]:
    print(f"  {course.code}: {course.name}")

# Show statistics courses
print("\n=== Statistics Courses ===")
stat_courses = [c for c in math_courses.values() if c.code.startswith("STAT")]
for course in sorted(stat_courses, key=lambda x: x.code):
    print(f"  {course.code}: {course.name} ({course.credits} cr)")
