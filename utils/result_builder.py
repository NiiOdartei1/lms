from datetime import datetime
from models import User, StudentProfile, SchoolSettings, ExamSubmission

class ResultBuilder:

    @staticmethod
    def build(student_id):
        """
        Build all variables required by any result template.
        student_id here is the integer primary key of User (current_user.id)
        """

        # --- GET USER ---
        user = User.query.get(student_id)

        if not user:
            # fallback if somehow the user doesn't exist
            student = {
                "name": "Unknown Student",
                "index_number": "-",
                "class_name": "-",
            }
            attendance = {"present": 0, "total": 0}
            teacher_remark = ""
            headteacher_remark = ""
            position = "-"
        else:
            # --- GET STUDENT PROFILE ---
            profile = getattr(user, "student_profile", None)

            student = {
                "name": user.full_name if user else "Unknown Student",
                "index_number": getattr(profile, "user_id", "-") if profile else "-",
                "class_name": getattr(profile, "current_class", "-") if profile else "-",
            }

            attendance = {
                "present": getattr(profile, "attendance_present", 0) if profile else 0,
                "total": getattr(profile, "attendance_total", 0) if profile else 0,
            }

            teacher_remark = getattr(profile, "teacher_remark", "") if profile else ""
            headteacher_remark = getattr(profile, "headteacher_remark", "") if profile else ""
            position = getattr(profile, "position", "-") if profile else "-"

        # --- SCHOOL INFO ---
        settings = SchoolSettings.query.first()
        school_info = {
            "school_name": getattr(settings, "school_name", "My School"),
            "school_address": getattr(settings, "school_address", ""),
            "school_logo": getattr(settings, "school_logo", ""),
        }
        term = getattr(settings, "current_term", "Term 1")
        year = getattr(settings, "academic_year", "2024 / 2025")

        # --- EXAM RESULTS ---
        exam_submissions = ExamSubmission.query.filter_by(student_id=user.user_id if user else None).all()
        results = []
        for sub in exam_submissions:
            exam = getattr(sub, "exam", None)
            total = getattr(sub, "score", 0) or 0
            grade = ResultBuilder.grade(total)
            results.append({
                "subject": getattr(exam, "subject", "Unknown"),
                "class_score": getattr(sub, "class_score", 0) or 0,
                "exam_score": getattr(sub, "score", 0) or 0,
                "total": total,
                "grade": grade,
                "remark": ResultBuilder.remark(grade),
            })

        # --- FINAL PAYLOAD ---
        return {
            "student": student,
            "results": results,
            "attendance": attendance,
            "teacher_remark": teacher_remark,
            "headteacher_remark": headteacher_remark,
            "position": position,
            "term": term,
            "year": year,
            **school_info,
            "now": datetime.utcnow().date(),
        }

    @staticmethod
    def grade(score):
        if score >= 80: return "A"
        if score >= 70: return "B"
        if score >= 60: return "C"
        if score >= 50: return "D"
        return "F"

    @staticmethod
    def remark(grade):
        mapping = {
            "A": "Excellent",
            "B": "Very Good",
            "C": "Good",
            "D": "Pass",
            "F": "Fail"
        }
        return mapping.get(grade, "")
