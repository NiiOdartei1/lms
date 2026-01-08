from models import SemesterResultRelease

class AcademicPeriodService:

    @staticmethod
    def get_current_released():
        """
        Returns the latest released academic year & semester
        """
        return (
            SemesterResultRelease.query
            .filter_by(is_released=True)
            .order_by(SemesterResultRelease.released_at.desc())
            .first()
        )
