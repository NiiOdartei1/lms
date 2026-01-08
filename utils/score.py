# utils/score.py

from models import StudentQuizSubmission

def calculate_student_score(user_id):
    submission = StudentQuizSubmission.query.filter_by(user_id=user_id).order_by(StudentQuizSubmission.submitted_at.desc()).first()
    if submission and submission.quiz and submission.quiz.questions:
        return (submission.score / len(submission.quiz.questions)) * 100
    return 0
