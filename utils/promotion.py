# utils/promotion.py

CLASS_PROGRESSIONS = [
    "KG", "Primary 1", "Primary 2", "Primary 3", "Primary 4", "Primary 5", "Primary 6",
    "JHS 1", "JHS 2", "JHS 3"
]

def promote_student(student, final_score):
    current_class = student.current_class

    if final_score >= 50:
        status = "Promoted"
        if current_class == "Primary 6":
            next_class = "JHS 1"
        elif current_class == "JHS 3":
            next_class = None
            status = "Graduated"
        else:
            try:
                current_index = CLASS_PROGRESSIONS.index(current_class)
                next_class = CLASS_PROGRESSIONS[current_index + 1]
            except (ValueError, IndexError):
                next_class = None
    elif 45 <= final_score < 50:
        status = "Probation"
        next_class = current_class
    else:
        status = "Repeat"
        next_class = current_class

    student.last_class_completed = current_class if status == "Promoted" else student.last_class_completed
    student.current_class = next_class if next_class else student.current_class
    student.academic_performance = status
