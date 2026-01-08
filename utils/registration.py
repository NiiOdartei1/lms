# utils/registration.py

from datetime import datetime
from app import db
from models import RegistrationDeadline  # or wherever your model is

def get_registration_deadline():
    deadline = RegistrationDeadline.query.order_by(RegistrationDeadline.id.desc()).first()
    return deadline.deadline if deadline else None
