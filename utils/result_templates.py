# utils/result_templates.py

TEMPLATE_MAP = {
    "basic": "results/basic.html",
    "shs": "results/shs.html",
    "university": "results/university.html",
}

TEMPLATE_LABELS = {
    "basic": "Basic Standard Template",
    "shs": "Senior High School Template",
    "university": "University Template",
}

def get_template_path(template_name: str) -> str:
    return TEMPLATE_MAP.get(template_name, TEMPLATE_MAP["basic"])

def get_available_templates() -> dict:
    return TEMPLATE_LABELS
