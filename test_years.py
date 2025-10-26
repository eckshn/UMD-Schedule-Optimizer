from optimizer.models.schedule import SemesterType

# Test semester sequence
current_year = 2025
current_sem_type = SemesterType.FALL
semester_sequence = []

for i in range(8):
    semester_sequence.append((current_year, current_sem_type))
    
    if current_sem_type == SemesterType.FALL:
        current_sem_type = SemesterType.SPRING
    else:
        current_sem_type = SemesterType.FALL
        current_year += 1

for year, sem_type in semester_sequence:
    print(f"{sem_type.value} {year}")
