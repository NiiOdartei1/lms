import uuid
from flask import url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property
import secrets, hashlib, json
from sqlalchemy.dialects.postgresql import JSON as PG_JSON 
from sqlalchemy import Column, Integer, String, Date, Time, Text
from utils.extensions import db

class Admin(db.Model, UserMixin):
    __tablename__ = 'admin'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    admin_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    last_seen = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"admin:{self.public_id}"

    @property
    def role(self):
        return 'admin'

    @property
    def is_admin(self):
        # Since this class is specifically Admin, return True
        return True
    
    @property
    def display_name(self):
        return self.username

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(20), unique=True, nullable=False)  # e.g. STD001, TCH001, PAR001
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # email used for password reset
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    profile_picture = db.Column(db.String(255), nullable=True, default="default.png")
    last_seen = db.Column(db.DateTime, nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey('school_class.id'), nullable=True)
    
    school_class = db.relationship('SchoolClass', backref='students')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"user:{self.public_id}"
    
    @property
    def is_student(self):
        return self.role == 'student'

    @property
    def is_teacher(self):
        return self.role == 'teacher'
    
    @property
    def full_name(self):
        names = [self.first_name]
        if self.middle_name:
            names.append(self.middle_name)
        names.append(self.last_name)
        return ' '.join(names)
    
    @property
    def display_name(self):
        return self.full_name
    
    @property
    def profile_picture_url(self):
        """Return the URL for the user's profile picture (fallback to default)."""
        if self.profile_picture:
            return url_for("static", filename=f"uploads/profile_pictures/{self.profile_picture}")
        return url_for("static", filename="uploads/profile_pictures/default.png")
    
    @property
    def unique_id(self):
        """Return a universal unique ID across all user roles"""
        if hasattr(self, 'user_id'):
            return self.user_id
        elif hasattr(self, 'admin_id'):
            return self.admin_id
        return str(self.id)


class PasswordResetRequest(db.Model):
    __tablename__ = 'password_reset_request'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), default='emailed')  
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    email_sent_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    user = db.relationship('User', backref='reset_requests')

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_token'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)
    token_hash = db.Column(db.String(128), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime)
    request_id = db.Column(db.Integer, db.ForeignKey('password_reset_request.id'))
    
    user = db.relationship('User', backref=db.backref('reset_tokens', cascade='all, delete-orphan'))
    request = db.relationship('PasswordResetRequest', backref=db.backref('tokens', cascade='all, delete-orphan'))

    @staticmethod
    def generate_for_user(user, request_obj=None, expires_in_minutes=60):
        import secrets, hashlib
        raw = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        now = datetime.utcnow()
        token = PasswordResetToken(
            user_id=user.user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(minutes=expires_in_minutes),
            request=request_obj
        )
        db.session.add(token)
        db.session.commit()
        return raw

    @staticmethod
    def verify(raw_token):
        import hashlib
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
        if not token:
            return None, 'invalid'
        if token.used:
            return None, 'used'
        if token.expires_at < datetime.utcnow():
            return None, 'expired'
        return token, 'ok'
        
class SchoolClass(db.Model):
    __tablename__ = 'school_class'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return f"<SchoolClass {self.name}>"

class SchoolSettings(db.Model):
    __tablename__ = "school_settings"
    id = db.Column(db.Integer, primary_key=True)
    school_name = db.Column(db.String(255), nullable=False)
    current_academic_year = db.Column(db.String(20), nullable=False)
    current_semester = db.Column(db.String(20), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), unique=True)
    graduated_level = db.Column(db.String(10))  # e.g., 'Primary', 'JHS', 'SHS'
    is_graduated = db.Column(db.Boolean, default=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10))
    nationality = db.Column(db.String(50))
    religion = db.Column(db.String(50))
    address = db.Column(db.Text)
    city = db.Column(db.String(50))
    state = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    guardian_name = db.Column(db.String(100))
    guardian_relation = db.Column(db.String(50))
    guardian_contact = db.Column(db.String(20))
    previous_school = db.Column(db.String(150))
    last_class_completed = db.Column(db.String(50))
    academic_performance = db.Column(db.String(100))
    current_class = db.Column(db.String(50))  # e.g., 'SHS 3'
    academic_year = db.Column(db.String(20))
    preferred_second_language = db.Column(db.String(50))
    sibling_name = db.Column(db.String(100))
    sibling_class = db.Column(db.String(50))
    blood_group = db.Column(db.String(10))
    medical_conditions = db.Column(db.Text)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_number = db.Column(db.String(20))

    user = db.relationship('User', backref=db.backref('student_profile', uselist=False), foreign_keys=[user_id])
    bookings = db.relationship('AppointmentBooking', back_populates='student', cascade='all, delete-orphan')

class TeacherProfile(db.Model):
    __tablename__ = 'teacher_profile'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), unique=True)
    employee_id = db.Column(db.String(20), unique=True, nullable=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    nationality = db.Column(db.String(50), nullable=True)
    qualification = db.Column(db.String(100), nullable=True)
    specialization = db.Column(db.String(100), nullable=True)
    years_of_experience = db.Column(db.Integer, nullable=True)
    subjects_taught = db.Column(db.String(255), nullable=True)
    employment_type = db.Column(db.String(20), nullable=True)  # e.g., Full-Time, Part-Time
    department = db.Column(db.String(100), nullable=True)
    date_of_hire = db.Column(db.Date, nullable=True)
    office_location = db.Column(db.String(100), nullable=True)
    date_joined = db.Column(db.Date, default=datetime.utcnow)

    user = relationship('User', backref=backref('teacher_profile', uselist=False), foreign_keys=[user_id])
    slots = db.relationship('AppointmentSlot', back_populates='teacher', cascade='all, delete-orphan')

class ParentChildLink(db.Model):
    __tablename__ = 'parent_child_link'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parent_profile.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)

    parent = db.relationship('ParentProfile', backref='children_links')
    student = db.relationship('StudentProfile', backref='parent_links')

class ParentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.user_id'), unique=True, nullable=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20))
    nationality = db.Column(db.String(100))
    occupation = db.Column(db.String(100))
    education_level = db.Column(db.String(150))
    phone_number = db.Column(db.String(20))
    email = db.Column(db.String(120))  # Optional: can differ from login email
    address = db.Column(db.String(255))
    relationship_to_student = db.Column(db.String(50))  # e.g., Mother, Father, Guardian
    number_of_children = db.Column(db.Integer)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))
    preferred_contact_method = db.Column(db.String(50))  # e.g., Phone, Email, SMS

    user = db.relationship("User", backref="parent_profile", uselist=False)

class ClassFeeStructure(db.Model):
    __tablename__ = 'class_fee_structure'
    id = db.Column(db.Integer, primary_key=True)
    class_level = db.Column(db.String(50), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    description = db.Column(db.String(255), nullable=False, default='Default')
    amount = db.Column(db.Float, nullable=False, default=0.0)
    try:
        items = db.Column(PG_JSON, nullable=False, server_default='[]')  # Postgres
    except Exception:
        items = db.Column(db.Text, nullable=False, default='[]')  # fallback for SQLite
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('class_level', 'academic_year', 'semester', 'description', name='uq_class_fee_group'),
    )

    # Helper properties for Text fallback
    @property
    def items_list(self):
        # returns python list of items
        if isinstance(self.items, str):
            try:
                return json.loads(self.items)
            except:
                return []
        return self.items or []

    @items_list.setter
    def items_list(self, val):
        if isinstance(self.items, str) or not hasattr(self.items, 'keys'):
            self.items = json.dumps(val)
        else:
            self.items = val

class StudentFeeTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    proof_filename = db.Column(db.String(255))  # uploaded file
    is_approved = db.Column(db.Boolean, default=False)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'))

    student = db.relationship('User', backref='fee_transactions')
    reviewer = db.relationship('Admin', backref='approved_payments', foreign_keys=[reviewed_by_admin_id])
        
class StudentFeeBalance(db.Model):
    __tablename__ = 'student_fee_balance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    updated_on = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = db.relationship('User', backref='fee_balances')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'academic_year', 'semester', name='uq_student_fee_balance'),
    )

class Quiz(db.Model):
    __tablename__ = 'quiz'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    assigned_class = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    attempts_allowed = db.Column(db.Integer, nullable=False, default=1)
    content_file = db.Column(db.String(255), nullable=True)

    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship('StudentQuizSubmission', backref='quiz', lazy=True, cascade="all, delete-orphan")
    attempts = db.relationship('QuizAttempt', backref='quiz', lazy=True, cascade="all, delete-orphan")

    @property
    def subject(self):
        return self.course_name

    @subject.setter
    def subject(self, value):
        self.course_name = value

    @property
    def max_score(self):
        return sum(q.points for q in self.questions or [])

class Question(db.Model):
    __tablename__ = 'question'
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    points = db.Column(db.Float, default=1.0, nullable=False)
    question_type = db.Column(db.String(50), nullable=False, default="mcq")

    options = db.relationship('Option', backref='question', cascade="all, delete-orphan")

    @property
    def max_score(self):
        return float(self.points or 0.0)

class Option(db.Model):
    __tablename__ = 'option'
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

class StudentAnswer(db.Model):
    __tablename__ = 'student_answers'
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('quiz_attempt.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    selected_option_id = db.Column(db.Integer, db.ForeignKey('option.id'), nullable=True)
    answer_text = db.Column(db.Text, nullable=True)
    is_correct = db.Column(db.Boolean, default=False)

    attempt = db.relationship('QuizAttempt', backref='answers')
    question = db.relationship('Question', backref='student_answers')


class StudentQuizSubmission(db.Model):
    __tablename__ = 'student_quiz_submissions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    score = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', backref='quiz_submissions')
        
class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(100), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    instructions = db.Column(db.Text)
    assigned_class = db.Column(db.String(50), nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    filename = db.Column(db.String(200))
    original_name = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    max_score = db.Column(db.Float, nullable=False)

class AssignmentSubmission(db.Model):
    __tablename__ = 'assignment_submissions'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float, nullable=True)
    feedback = db.Column(db.Text, nullable=True)
    scored_at = db.Column(db.DateTime)
    grade_letter = db.Column(db.String(5))   # e.g. A, B+, C, etc.
    pass_fail = db.Column(db.String(10))     # e.g. Pass, Fail

    student = db.relationship("User", backref="assignment_submissions")
    assignment = db.relationship("Assignment", backref="submissions")

class GradingScale(db.Model):
    __tablename__ = 'grading_scales'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    min_score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    grade_letter = db.Column(db.String(5), nullable=False)
    pass_fail = db.Column(db.String(10), nullable=False)
    created_by_admin = db.Column(db.Boolean, default=True)

class CourseMaterial(db.Model):
    __tablename__ = 'course_material'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    assigned_class = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

from sqlalchemy.sql import func

class Course(db.Model):
    __tablename__ = 'course'
    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(100), nullable=False)
    code                = db.Column(db.String(20), unique=True, nullable=False)
    assigned_class      = db.Column(db.String(50), nullable=False)
    semester            = db.Column(db.String(10), nullable=False)
    credit_hours        = db.Column(db.Integer, default=3)
    academic_year       = db.Column(db.String(20), nullable=False)
    is_mandatory        = db.Column(db.Boolean, default=False)
    registration_start  = db.Column(db.DateTime, nullable=True)
    registration_end    = db.Column(db.DateTime, nullable=True)

    @classmethod
    def get_registration_window(cls):
        """Return a tuple (start, end) of the global registration window."""
        result = db.session.query(
            func.min(cls.registration_start),
            func.max(cls.registration_end)
        ).one()
        return result  # (start_datetime, end_datetime)

    @classmethod
    def set_registration_window(cls, start_dt, end_dt):
        """Apply the same window to every course."""
        db.session.query(cls).update({
            cls.registration_start: start_dt,
            cls.registration_end:   end_dt
        })
        db.session.commit()

class CourseLimit(db.Model):
    __tablename__ = 'course_limit'
    id               = db.Column(db.Integer, primary_key=True)
    class_level      = db.Column(db.String(50), nullable=False)  # e.g. 'JHS 1'
    semester         = db.Column(db.String(10), nullable=False)
    academic_year    = db.Column(db.String(20), nullable=False)
    mandatory_limit  = db.Column(db.Integer, nullable=False)
    optional_limit   = db.Column(db.Integer, nullable=False)

class StudentCourseRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)

    course = db.relationship('Course', backref='registrations')
    student = db.relationship('User', backref='registered_courses')

class SemesterResultRelease(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    is_released = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    released_at = db.Column(db.DateTime)

class TimetableEntry(db.Model):
    __tablename__ = 'timetable_entry'
    id = db.Column(db.Integer, primary_key=True)
    assigned_class = db.Column(db.String(50), nullable=False)  # e.g., "JSS1"
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    day_of_week = db.Column(db.String(10), nullable=False)  # e.g., "Monday"
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    course = db.relationship('Course', backref='timetable_entries')


class TeacherCourseAssignment(db.Model):
    __tablename__ = 'teacher_course_assignment'
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_profile.id'), nullable=False)
    course_id  = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)

    teacher = db.relationship("TeacherProfile", backref="assignments")
    course  = db.relationship("Course")

class CourseAssessmentScheme(db.Model):
    __tablename__ = "course_assessment_schemes"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=False)
    quiz_weight = db.Column(db.Float, nullable=False, default=0)
    assignment_weight = db.Column(db.Float, nullable=False, default=0)
    exam_weight = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("course_id", "teacher_id", name="uix_course_teacher_scheme"),
    )

    @property
    def total_weight(self):
        return self.quiz_weight + self.assignment_weight + self.exam_weight

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_record'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_profile.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    is_present = db.Column(db.Boolean, default=False)

    student = db.relationship('User')
    teacher = db.relationship('TeacherProfile')
    course = db.relationship('Course')

class AcademicCalendar(db.Model):
    __tablename__ = 'academic_calendar'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    label = db.Column(db.String(100), nullable=False)
    break_type = db.Column(db.String(50), nullable=False)  # e.g. Holiday, Exam, Midterm
    is_workday = db.Column(db.Boolean, default=False)

class AcademicYear(db.Model):
    __tablename__ = 'academic_year'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    semester_1_start = db.Column(db.Date, nullable=False)
    semester_1_end = db.Column(db.Date, nullable=False)
    semester_2_start = db.Column(db.Date, nullable=False)
    semester_2_end = db.Column(db.Date, nullable=False)

class AppointmentSlot(db.Model):
    __tablename__ = 'appointment_slot'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_profile.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_booked = db.Column(db.Boolean, default=False, nullable=False)

    teacher = db.relationship('TeacherProfile', back_populates='slots')
    booking = db.relationship('AppointmentBooking', back_populates='slot', uselist=False)

class AppointmentBooking(db.Model):
    __tablename__ = 'appointment_booking'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('appointment_slot.id'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, approved, declined, rescheduled
    note = db.Column(db.Text)
    requested_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship('StudentProfile', back_populates='bookings')
    slot = db.relationship('AppointmentSlot', back_populates='booking')


# ============================
# Exam-related models
# ============================
class Exam(db.Model):
    __tablename__ = 'exams'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    assigned_class = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=True)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignment_mode = db.Column(db.String(20), default='random', nullable=False)
    assignment_seed = db.Column(db.String(255), nullable=True)

    questions = db.relationship('ExamQuestion', backref='exam', cascade="all, delete-orphan")
    sets = db.relationship("ExamSet", backref="exam", cascade="all, delete-orphan")
    submissions = db.relationship('ExamSubmission', backref='exam', cascade="all, delete-orphan")
    course = db.relationship('Course', backref='exams')

    def __repr__(self):
        return f"<Exam {self.title}>"

    @hybrid_property
    def max_score(self):
        return sum(q.marks for q in self.questions or [])

class ExamSet(db.Model):
    __tablename__ = "exam_sets"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    max_score = db.Column(db.Float, nullable=True)
    access_password = db.Column(db.String(128), nullable=True)

    set_questions = db.relationship("ExamSetQuestion", backref="set", cascade="all, delete-orphan")

    @property
    def password(self):
        return self.access_password

    def __repr__(self):
        return f"<ExamSet {self.name} of Exam {self.exam_id}>"

    @property
    def computed_max_score(self):
        return sum(q.question.marks or 0 for q in self.set_questions)

class ExamQuestion(db.Model):
    __tablename__ = "exam_questions"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # 'mcq', 'true_false', 'subjective'
    marks = db.Column(db.Integer, nullable=False, default=1)

    options = db.relationship("ExamOption", backref="question", cascade="all, delete-orphan")
    in_sets = db.relationship("ExamSetQuestion", backref="question", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ExamQuestion {self.question_text[:30]}...>"

class ExamSetQuestion(db.Model):
    __tablename__ = 'exam_set_questions'
    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.Integer, db.ForeignKey("exam_sets.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_questions.id"), nullable=False)
    order = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("set_id", "question_id", name="uix_set_question"),
    )

class ExamOption(db.Model):
    __tablename__ = 'exam_options'
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('exam_questions.id'), nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<ExamOption {self.text}>"

# ============================
# Attempts / Submissions
# ============================
class ExamAttempt(db.Model):
    __tablename__ = 'exam_attempts'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey('exam_sets.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    submitted = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, nullable=True)   # exact submission time
    score = db.Column(db.Float, nullable=True)

    exam = db.relationship("Exam", backref="attempts")
    exam_set = db.relationship("ExamSet", backref="attempts")

    def __repr__(self):
        return f"<ExamAttempt exam={self.exam_id} student={self.student_id} submitted={self.submitted}>"

class ExamSubmission(db.Model):
    __tablename__ = 'exam_submissions'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey('exam_sets.id'), nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float, nullable=True)

    answers = db.relationship('ExamAnswer', backref='submission', cascade="all, delete-orphan")
    exam_set = db.relationship("ExamSet", backref="submissions")

    __table_args__ = (
        db.UniqueConstraint('exam_id', 'student_id', name='uix_exam_student'),
    )

    def __repr__(self):
        return f"<ExamSubmission exam={self.exam_id} student={self.student_id}>"

    @property
    def max_score(self):
        if self.exam_set:  # ✅ always prioritize the set
            return self.exam_set.computed_max_score or 0
        return 0  # if no set was assigned, don't fall back to exam pool

class ExamAnswer(db.Model):
    __tablename__ = 'exam_answers'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('exam_submissions.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('exam_questions.id'), nullable=False)
    selected_option_id = db.Column(db.Integer, db.ForeignKey('exam_options.id'), nullable=True)
    answer_text = db.Column(db.Text, nullable=True)  # for subjective answers

    def __repr__(self):
        return f"<ExamAnswer Q{self.question_id} -> Option {self.selected_option_id or 'text'}>"

class ExamTimetableEntry(db.Model):
    __tablename__ = 'exam_timetable_entries'
    id = Column(Integer, primary_key=True)
    assigned_class = Column(String(64), nullable=False)    # e.g. "Level 300"
    student_index = Column(String(64), nullable=True)       # optional: student-specific entry; usually NULL
    course = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    room = Column(String(64))
    building = Column(String(128))
    floor = Column(String(64))
    notes = Column(Text, nullable=True)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # e.g. 'assignment', 'quiz', 'exam', 'event', 'fee', 'general'
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Support both user and admin senders
    sender_id = db.Column(db.String(20), nullable=True)  # Can be user_id or admin_id
    sender_type = db.Column(db.String(10), default='user', nullable=False)  # 'user' or 'admin'
    
    related_type = db.Column(db.String(50), nullable=True)
    related_id = db.Column(db.Integer, nullable=True)
    
    # Define relationships with foreign_keys parameter
    user_sender = db.relationship(
        'User',
        foreign_keys='Notification.sender_id',
        primaryjoin="and_(Notification.sender_id==User.user_id, Notification.sender_type=='user')",
        viewonly=True,
        lazy='joined'
    )
    
    admin_sender = db.relationship(
        'Admin',
        foreign_keys='Notification.sender_id',
        primaryjoin="and_(Notification.sender_id==Admin.admin_id, Notification.sender_type=='admin')",
        viewonly=True,
        lazy='joined'
    )
    
    recipients = db.relationship(
        "NotificationRecipient",
        back_populates="notification",
        cascade="all, delete-orphan"
    )
    
    @property
    def sender(self):
        """Get the sender object (User or Admin)"""
        if self.sender_type == 'admin':
            return self.admin_sender
        return self.user_sender
    
    @property
    def sender_name(self):
        """Get the sender's display name"""
        sender = self.sender
        if sender:
            return sender.display_name
        return "Unknown"

class NotificationRecipient(db.Model):
    __tablename__ = 'notification_recipients'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=False)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    notification = db.relationship('Notification', back_populates='recipients')

    user = db.relationship('User', backref='notifications_received')

class Meeting(db.Model):
    __tablename__ = 'meetings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    meeting_code = db.Column(db.String(80), unique=True, index=True, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    scheduled_start = db.Column(db.DateTime, nullable=True)
    scheduled_end = db.Column(db.DateTime, nullable=True)
    join_url = db.Column(db.String(500))   # <-- Zoom join URL
    start_url = db.Column(db.String(500))  # <-- Zoom host start URL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    host = db.relationship('User', backref='meetings')
    course = db.relationship('Course', backref='meetings')
    recordings = db.relationship('Recording', backref='meeting', lazy='dynamic')

class Recording(db.Model):
    __tablename__ = 'recordings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)  # local path or streaming URL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    meeting_id = db.Column(db.Integer, db.ForeignKey('meetings.id'))

    teacher = db.relationship('User', backref='recordings')
    course = db.relationship('Course', backref='recordings')

class Conversation(db.Model):
    __tablename__ = "conversation"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # direct | broadcast | class
    meta_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = db.relationship("ConversationParticipant", backref="conversation", cascade="all, delete-orphan")
    messages = db.relationship("Message", backref="conversation", cascade="all, delete-orphan", order_by="Message.created_at.asc()")

    def get_meta(self):
        return json.loads(self.meta_json or "{}")

    def set_meta(self, data: dict):
        self.meta_json = json.dumps(data) if data else None

class ConversationParticipant(db.Model):
    __tablename__ = "conversation_participant"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    user_public_id = db.Column(db.String(36), nullable=False)  # <- UUID string
    user_role = db.Column(db.String(20), nullable=False)  # 'student','teacher','admin','parent'
    is_group_admin = db.Column(db.Boolean, default=False, nullable=False)
    can_add_members = db.Column(db.Boolean, default=False, nullable=False)
    can_remove_members = db.Column(db.Boolean, default=False, nullable=False)
    can_rename_group = db.Column(db.Boolean, default=False, nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_read_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("conversation_id", "user_public_id", "user_role", name="uq_conv_user_role_pub"),
    )

    @property
    def participant_obj(self):
        if self.user_role == 'admin':
            return Admin.query.filter_by(public_id=self.user_public_id).first()
        return User.query.filter_by(public_id=self.user_public_id).first()

class Message(db.Model):
    __tablename__ = "message"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    sender_public_id = db.Column(db.String(36), nullable=False)    # <- UUID string
    sender_role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reply_to_message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    edited_by = db.Column(db.String(36), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.String(36), nullable=True)

    reply_to = db.relationship("Message", remote_side=[id], backref="replies")

    def to_dict(self):
        sender_name = None
        if self.sender_role == "admin":
            admin = Admin.query.filter_by(public_id=self.sender_public_id).first()
            if admin:
                sender_name = admin.username
        else:
            user = User.query.filter_by(public_id=self.sender_public_id).first()
            if user:
                sender_name = user.full_name

        content = self.content
        if self.is_deleted:
            # show deleted placeholder to clients
            content = "[message deleted]"

        reply_to_data = None
        if self.reply_to and not self.reply_to.is_deleted:
            reply_sender_name = None
            if self.reply_to.sender_role == "admin":
                admin = Admin.query.filter_by(public_id=self.reply_to.sender_public_id).first()
                if admin:
                    reply_sender_name = admin.username
            else:
                user = User.query.filter_by(public_id=self.reply_to.sender_public_id).first()
                if user:
                    reply_sender_name = user.full_name
            reply_to_data = {
                "id": self.reply_to.id,
                "sender_name": reply_sender_name or f"{self.reply_to.sender_role.capitalize()} {self.reply_to.sender_public_id}",
                "content": self.reply_to.content[:100] + "..." if len(self.reply_to.content) > 100 else self.reply_to.content,
                "created_at": self.reply_to.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }

        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender_public_id": self.sender_public_id,
            "sender_role": self.sender_role,
            "sender_name": sender_name or f"{self.sender_role.capitalize()} {self.sender_public_id}",
            "content": content,
            "raw_content": None if self.is_deleted else self.content,  # keep raw for copy if client requests
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "reply_to_message_id": self.reply_to_message_id,
            "reply_to": reply_to_data,
            "edited_at": self.edited_at.strftime("%Y-%m-%d %H:%M:%S") if self.edited_at else None,
            "edited_by": self.edited_by,
            "is_deleted": bool(self.is_deleted),
            "deleted_at": self.deleted_at.strftime("%Y-%m-%d %H:%M:%S") if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

class MessageReaction(db.Model):
    __tablename__ = "message_reaction"
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=False)
    user_public_id = db.Column(db.String(36), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)  # e.g., "👍"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "user_public_id": self.user_public_id,
            "emoji": self.emoji,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

class TeacherAssessmentPeriod(db.Model):
    __tablename__ = 'teacher_assessment_period'
    id = db.Column(db.Integer, primary_key=True)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeacherAssessmentQuestion(db.Model):
    __tablename__ = 'teacher_assessment_question'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50))  
    question = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class TeacherAssessment(db.Model):
    __tablename__ = 'teacher_assessment'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('user.user_id'))
    teacher_id = db.Column(db.String(20), db.ForeignKey('user.user_id'))
    class_name = db.Column(db.String(50))
    course_name = db.Column(db.String(100))
    period_id = db.Column(db.Integer, db.ForeignKey('teacher_assessment_period.id'))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            'student_id', 'teacher_id', 'course_name', 'period_id',
            name='unique_teacher_assessment'
        ),
    )

class TeacherAssessmentAnswer(db.Model):
    __tablename__ = 'teacher_assessment_answer'
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('teacher_assessment.id'))
    question_id = db.Column(db.Integer, db.ForeignKey('teacher_assessment_question.id'))
    score = db.Column(db.Integer)  

    assessment = db.relationship('TeacherAssessment', backref='answers')
    question = db.relationship('TeacherAssessmentQuestion')


