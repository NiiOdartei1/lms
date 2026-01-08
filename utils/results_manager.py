# utils/results_manager.py

from utils.extensions import db
from models import SchoolSettings

DEFAULT_TEMPLATE = "basic"

class ResultManager:
    @staticmethod
    def get_template_name() -> str:
        settings = SchoolSettings.query.first()
        return settings.result_template if settings else DEFAULT_TEMPLATE

    @staticmethod
    def set_template_name(template_name: str):
        settings = SchoolSettings.query.first()
        if not settings:
            settings = SchoolSettings(result_template=template_name)
            db.session.add(settings)
        else:
            settings.result_template = template_name
        db.session.commit()

    @staticmethod
    def get_available_templates():
        return {
            "basic": "Basic School Template",
            "shs": "Senior High Template",
            "university": "University Template"
        }
