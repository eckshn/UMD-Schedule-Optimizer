from pathlib import Path
from optimizer.data.loader import DataLoader

loader = DataLoader(Path("sample_data"))
math_courses = loader.load_courses("MATH")

math140 = math_courses["MATH140"]
print(f"MATH140: {math140.name}")
print(f"Prerequisites: {len(math140.prerequisites)}")
for prereq in math140.prerequisites:
    print(f"  Type: {prereq.type.value}")
    print(f"  Courses: {prereq.courses}")
    print(f"  Min grade: {prereq.min_grade}")
