from datetime import datetime, timedelta
from utils.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class Applicant(db.Model, UserMixin):
    __tablename__ = 'applicant'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    email_verified = db.Column(db.Boolean, default=False)
    email_verification_code = db.Column(db.String(6))
    email_verification_expires = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    application = db.relationship('Application', backref='applicant', uselist=False, cascade='all, delete-orphan')
    payments = db.relationship('ApplicationPayment', backref='applicant', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Application(db.Model):
    __tablename__ = 'application'

    id = db.Column(db.Integer, primary_key=True)
    applicant_id = db.Column(db.Integer, db.ForeignKey('applicant.id'), nullable=False, unique=True)

    # Personal info
    title = db.Column(db.String(10), nullable=True)
    surname = db.Column(db.String(100), nullable=True)
    other_names = db.Column(db.String(150), nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    dob = db.Column(db.Date, nullable=True)
    nationality = db.Column(db.String(50), nullable=True)
    marital_status = db.Column(db.String(20), nullable=True)
    home_region = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    postal_address = db.Column(db.String(255), nullable=True)

    # Guardian info
    guardian_name = db.Column(db.String(150), nullable=True)
    guardian_relation = db.Column(db.String(50), nullable=True)
    guardian_occupation = db.Column(db.String(100), nullable=True)
    guardian_phone = db.Column(db.String(20), nullable=True)
    guardian_email = db.Column(db.String(120), nullable=True)
    guardian_address = db.Column(db.String(255), nullable=True)

    # Programme choices
    first_choice = db.Column(db.String(100), nullable=True)
    first_stream = db.Column(db.String(50), nullable=True)
    second_choice = db.Column(db.String(100), nullable=True)
    second_stream = db.Column(db.String(50), nullable=True)
    third_choice = db.Column(db.String(100), nullable=True)
    third_stream = db.Column(db.String(50), nullable=True)
    fourth_choice = db.Column(db.String(100), nullable=True)
    fourth_stream = db.Column(db.String(50), nullable=True)

    # Application lifecycle
    status = db.Column(db.String(30), default='draft')
    submitted_at = db.Column(db.DateTime)

    # Relationships
    documents = db.relationship('ApplicationDocument', backref='application', cascade='all, delete-orphan')
    exam_results = db.relationship('ApplicationResult', backref='application', cascade='all, delete-orphan')


class ApplicationDocument(db.Model):
    __tablename__ = 'application_document'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'), nullable=False)
    document_type = db.Column(db.String(50))  # transcript, certificate, photo
    file_path = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdmissionVoucher(db.Model):
    __tablename__ = 'admission_voucher'
    id = db.Column(db.Integer, primary_key=True)
    pin = db.Column(db.String(20), unique=True, nullable=False)
    serial = db.Column(db.String(20), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    is_used = db.Column(db.Boolean, default=False)
    used_by = db.Column(db.Integer, db.ForeignKey('applicant.id'), nullable=True)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime, nullable=True)
    purchaser_email = db.Column(db.String(120), nullable=True)

    def mark_as_used(self, applicant_id):
        """Mark voucher as used by this applicant"""
        self.is_used = True
        self.used_by = applicant_id
        if not self.used_at:
            self.used_at = datetime.utcnow()
        if not self.valid_until:
            self.valid_until = datetime.utcnow() + timedelta(days=180)

    def is_available_for(self, applicant_id):
        """
        Check if voucher can be used:
        - Either unused, or already used by this applicant
        """
        if not self.is_used:
            return True
        if self.used_by == applicant_id:
            return True
        return False


class ApplicationResult(db.Model):
    __tablename__ = 'application_result'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'), nullable=False)

    exam_type = db.Column(db.String(50))  # WASSCE, A-Level, IB, etc.
    index_number = db.Column(db.String(50))
    exam_year = db.Column(db.String(10))
    school_name = db.Column(db.String(150))

    subject = db.Column(db.String(100))
    grade = db.Column(db.String(5))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ApplicationPayment(db.Model):
    __tablename__ = 'application_payment'

    id = db.Column(db.Integer, primary_key=True)
    applicant_id = db.Column(db.Integer, db.ForeignKey('applicant.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(50))  # momo, card, voucher
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
