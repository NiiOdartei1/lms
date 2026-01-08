from services.academic_period_service import AcademicPeriodService
from services.result_engine import UniversityResultEngine
from models import Course, StudentCourseRegistration


class ResultBuilder:

    @staticmethod
    def semester(student_id, academic_year=None, semester=None):

        # Resolve academic period dynamically
        if not academic_year or not semester:
            release = AcademicPeriodService.get_current_released()
            if not release:
                return {
                    "results": [],
                    "academic_year": None,
                    "semester": None,
                    "released": False
                }

            academic_year = release.academic_year
            semester = release.semester

        courses = (
            Course.query
            .join(StudentCourseRegistration)
            .filter(
                StudentCourseRegistration.student_id == student_id,
                Course.academic_year == academic_year,
                Course.semester == semester
            )
            .all()
        )

        results = []
        for course in courses:
            cr = UniversityResultEngine.compute_course(student_id, course)
            if cr:
                results.append(cr)

        return {
            "results": results,
            "academic_year": academic_year,
            "semester": semester,
            "released": True
        }

    @staticmethod
    def transcript(student_id):
        # Get all courses for the student
        from models import Course, StudentCourseRegistration
        registrations = StudentCourseRegistration.query.filter_by(student_id=student_id).all()
        course_ids = [r.course_id for r in registrations]
        courses = Course.query.filter(Course.id.in_(course_ids)).all()

        # Group by academic_year and semester
        grouped = {}
        all_grades = []
        for course in courses:
            key = (course.academic_year, course.semester)
            if key not in grouped:
                grouped[key] = []
            cr = UniversityResultEngine.compute_course(student_id, course)
            if cr:
                grouped[key].append(cr)
                if "grade" in cr:
                    all_grades.append(cr["grade"])

        # Calculate overall GPA
        gpa_mapping = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
        if all_grades:
            total_points = sum(gpa_mapping.get(grade, 0) for grade in all_grades)
            overall_gpa = total_points / len(all_grades)
        else:
            overall_gpa = 0.0

        return {
            "records": grouped,
            "overall_gpa": round(overall_gpa, 2)
        }
