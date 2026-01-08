from models import GradingScale

class GradeService:
    @staticmethod
    def get_grade(percent):
        if percent is None:
            return None

        return (
            GradingScale.query
            .filter(GradingScale.min_score <= percent)
            .filter(GradingScale.max_score >= percent)
            .first()
        )
