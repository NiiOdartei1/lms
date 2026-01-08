class AssessmentEngine:
    @staticmethod
    def percent(score, max_score):
        if score is None or not max_score or max_score <= 0:
            return 0.0
        return round((score / max_score) * 100, 2)
