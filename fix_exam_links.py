# fix_exam_links.py
from app import app, db
from models import Exam, ExamQuestion

with app.app_context():
    all_exams = Exam.query.all()
    fixed_count = 0

    for exam in all_exams:
        # Find questions not linked to this exam
        unlinked_questions = ExamQuestion.query.filter(
            (ExamQuestion.exam_id.is_(None)) | (ExamQuestion.exam_id != exam.id)
        ).all()

        for q in unlinked_questions:
            q.exam_id = exam.id
            fixed_count += 1

    db.session.commit()
    print(f"✅ Fixed {fixed_count} exam question(s) links.")
