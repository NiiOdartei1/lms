from models import (
    db, Quiz, StudentQuizSubmission,
    Assignment, AssignmentSubmission,
    Exam, ExamSubmission, CourseAssessmentScheme
)
from services.assessment_engine import AssessmentEngine
from services.grade_service import GradeService


class UniversityResultEngine:

    @staticmethod
    def compute_course(student_id, course):
        scheme = CourseAssessmentScheme.query.filter_by(course_id=course.id).first()
        if not scheme:
            return None

        quiz_avg = UniversityResultEngine._quiz_avg(student_id, course)
        assignment_avg = UniversityResultEngine._assignment_avg(student_id, course)
        exam_score = UniversityResultEngine._exam_score(student_id, course)

        final_score = (
            quiz_avg * scheme.quiz_weight / 100 +
            assignment_avg * scheme.assignment_weight / 100 +
            exam_score * scheme.exam_weight / 100
        )

        final_score = round(final_score, 2)
        grade = GradeService.get_grade(final_score)

        return {
            "course": course,
            "score": final_score,
            "grade": grade.grade_letter if grade else None,
            "grade_point": grade.grade_point if grade else 0.0,
            "pass_fail": grade.pass_fail if grade else None,
            "credit_hours": course.credit_hours,
            "points": (grade.grade_point if grade else 0.0) * course.credit_hours
        }

    # ---------------- HELPERS ---------------- #

    @staticmethod
    def _quiz_avg(student_id, course):
        subs = (
            StudentQuizSubmission.query
            .join(Quiz)
            .filter(
                StudentQuizSubmission.student_id == student_id,
                Quiz.course_id == course.id
            ).all()
        )
        if not subs:
            return 0.0
        total_score = sum(s.score for s in subs if s.score is not None)
        total_max = sum(s.quiz.max_score for s in subs)
        return AssessmentEngine.percent(total_score, total_max)

    @staticmethod
    def _assignment_avg(student_id, course):
        subs = (
            AssignmentSubmission.query
            .join(Assignment)
            .filter(
                AssignmentSubmission.student_id == student_id,
                Assignment.course_id == course.id
            ).all()
        )
        if not subs:
            return 0.0
        total_score = sum(s.score for s in subs if s.score is not None)
        total_max = sum(s.assignment.max_score for s in subs)
        return AssessmentEngine.percent(total_score, total_max)

    @staticmethod
    def _exam_score(student_id, course):
        sub = (
            ExamSubmission.query
            .join(Exam)
            .filter(
                ExamSubmission.student_id == student_id,
                Exam.course_id == course.id
            )
            .order_by(ExamSubmission.submitted_at.desc())
            .first()
        )
        if not sub:
            return 0.0

        return AssessmentEngine.percent(sub.score, sub.exam.max_score)
