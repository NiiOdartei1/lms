from itsdangerous import URLSafeTimedSerializer
from flask import current_app

def generate_reset_token(user_id, expires_sec=3600):
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps(user_id, salt="password-reset")

def verify_reset_token(token, max_age=3600):
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        user_id = s.loads(token, salt="password-reset", max_age=max_age)
    except Exception:
        return None
    return user_id
