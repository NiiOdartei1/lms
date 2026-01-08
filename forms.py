from flask_wtf import FlaskForm
from wtforms import HiddenField, StringField, PasswordField, SubmitField, SelectField, DateField, TextAreaField, MultipleFileField, SelectMultipleField, BooleanField, IntegerField, FloatField, FieldList, FormField
from wtforms.validators import DataRequired, Length, InputRequired, Email, Optional, NumberRange, EqualTo, ValidationError
from wtforms.fields import DateTimeLocalField, DateTimeField
from flask_wtf.file import FileField, FileAllowed, FileRequired
from utils.helpers import get_class_choices
from datetime import datetime

class AdminLoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    user_id = StringField("Admin ID", validators=[DataRequired(), Length(min=3, max=20)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class StudentLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    user_id = StringField("Student ID", validators=[DataRequired(), Length(min=3, max=20)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class TeacherLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    user_id = StringField("Teacher ID", validators=[DataRequired(), Length(min=3, max=20)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class ParentLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    user_id = StringField("Parent ID", validators=[DataRequired(), Length(min=3, max=20)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class ExamLoginForm(FlaskForm):
    user_id = StringField("Student ID", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class AdminRegisterForm(FlaskForm):
    # 🔹 Core User fields
    first_name = StringField('First Name', validators=[InputRequired(), Length(min=1, max=100)])
    middle_name = StringField('Middle Name', validators=[Optional(), Length(max=100)])
    last_name = StringField('Last Name', validators=[InputRequired(), Length(min=1, max=100)])
    profile_picture = FileField(
        "Profile Picture",
        validators=[
            FileRequired(message="Profile picture is required."),
            FileAllowed(["jpg", "jpeg", "png", "gif"], "Images only!")
        ]
    )
    role = SelectField('Role', choices=[
        ('', 'Select Role'),
        ('student', 'Student'),
        ('teacher', 'Teacher'),
        ('parent', 'Parent')
    ], validators=[InputRequired()])

    username = StringField('Username', validators=[InputRequired(), Length(min=3, max=100)])
    email = StringField('Login Email', validators=[InputRequired(), Email(), Length(max=120)])
    password = PasswordField('Temporary Password', validators=[InputRequired(), Length(min=6)])

    # 🔹 Shared (Student/Teacher/Parent)
    dob = DateField('Date of Birth', format='%Y-%m-%d', validators=[Optional()])
    gender = SelectField('Gender', choices=[
        ('', 'Select Gender'),
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other')
    ], validators=[Optional()])
    nationality = StringField('Nationality', validators=[Optional(), Length(max=50)])

    # ============================
    # Student-specific profile
    # ============================
    religion = StringField('Religion', validators=[Optional(), Length(max=50)])
    blood_group = StringField('Blood Group', validators=[Optional(), Length(max=10)])
    medical_conditions = TextAreaField('Medical Conditions', validators=[Optional()])
    guardian_name = StringField('Guardian Name', validators=[Optional(), Length(max=100)])
    guardian_relation = StringField('Guardian Relation', validators=[Optional(), Length(max=50)])
    guardian_contact = StringField('Guardian Contact', validators=[Optional(), Length(max=20)])
    previous_school = StringField('Previous School', validators=[Optional(), Length(max=150)])
    last_class_completed = StringField('Last Class Completed', validators=[Optional(), Length(max=50)])
    academic_performance = StringField('Academic Performance', validators=[Optional(), Length(max=100)])
    current_class = SelectField('Desired Class', choices=get_class_choices(), validators=[Optional()])
    academic_year = StringField('Academic Year', validators=[Optional(), Length(max=20)])
    preferred_second_language = StringField('Preferred Second Language', validators=[Optional(), Length(max=50)])
    sibling_name = StringField('Sibling Name', validators=[Optional(), Length(max=100)])
    sibling_class = StringField('Sibling Class', validators=[Optional(), Length(max=50)])
    emergency_contact_name = StringField('Emergency Contact Name', validators=[Optional(), Length(max=100)])
    emergency_contact_number = StringField('Emergency Contact Number', validators=[Optional(), Length(max=20)])
    # Contact info (mapped to StudentProfile, not User)
    student_phone = StringField('Student Phone', validators=[Optional(), Length(max=20)])
    student_address = StringField('Student Address', validators=[Optional()])
    student_city = StringField('City', validators=[Optional(), Length(max=50)])
    student_state = StringField('State', validators=[Optional(), Length(max=50)])
    student_postal_code = StringField('Postal Code', validators=[Optional(), Length(max=20)])
    student_contact_email = StringField('Student Contact Email (optional)', validators=[Optional(), Email(), Length(max=100)])

    # ============================
    # Teacher-specific profile
    # ============================
    employee_id = StringField('Employee ID', validators=[Optional(), Length(max=50)])
    qualification = StringField('Qualification', validators=[Optional(), Length(max=100)])
    specialization = StringField('Specialization', validators=[Optional(), Length(max=100)])
    years_of_experience = IntegerField('Years of Experience', validators=[Optional(), NumberRange(min=0, max=100)])
    subjects_taught = StringField('Subjects Taught (comma-separated)', validators=[Optional(), Length(max=200)])
    employment_type = SelectField('Employment Type', choices=[
        ('', 'Select Type'),
        ('Full-time', 'Full-time'),
        ('Part-time', 'Part-time'),
        ('Contract', 'Contract')
    ], validators=[Optional()])
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    date_of_hire = DateField('Date of Hire', format='%Y-%m-%d', validators=[Optional()])
    office_location = StringField('Office Location', validators=[Optional()])

    # ============================
    # Parent-specific profile
    # ============================
    parent_dob = DateField('Date of Birth', format='%Y-%m-%d', validators=[Optional()])
    parent_gender = SelectField('Parent Gender', choices=[
        ('', 'Select Gender'),
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other')
    ], validators=[Optional()])
    parent_nationality = StringField('Nationality', validators=[Optional(), Length(max=50)])
    occupation = StringField('Occupation', validators=[Optional(), Length(max=100)])
    education_level = StringField('Education Level', validators=[Optional(), Length(max=100)])
    parent_contact_email = StringField('Parent Contact Email (optional)', validators=[Optional(), Email(), Length(max=120)])
    phone_number = StringField('Parent Phone', validators=[Optional(), Length(max=20)])
    parent_address = StringField('Parent Address', validators=[Optional()])
    relationship_to_student = StringField('Relationship to Student', validators=[Optional(), Length(max=50)])
    number_of_children = IntegerField('Number of Children', validators=[Optional(), NumberRange(min=0, max=20)])
    emergency_contact_name_parent = StringField('Emergency Contact Name', validators=[Optional(), Length(max=100)])
    emergency_contact_phone = StringField('Emergency Contact Phone', validators=[Optional(), Length(max=20)])
    preferred_contact_method = SelectField('Preferred Contact Method', choices=[
        ('', 'Select Method'),
        ('Phone', 'Phone'),
        ('Email', 'Email'),
        ('SMS', 'SMS')
    ], validators=[Optional()])
    child_student_ids = SelectMultipleField('Select Child(ren)', choices=[], coerce=int, validators=[Optional()])

    # ============================
    submit = SubmitField('Register User')

class ForgotPasswordForm(FlaskForm):
    # Ask the user for the email they registered with (recommended)
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    user_id = StringField('User ID (optional)', validators=[Length(max=20)])
    submit = SubmitField('Send Reset Email')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New password', validators=[DataRequired(), Length(min=8, message='Minimum 8 characters')])
    confirm_password = PasswordField('Confirm password', validators=[DataRequired(), EqualTo('password', message='Passwords must match')])
    submit = SubmitField('Set New Password')

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message="Password must be at least 6 characters")
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message="Passwords must match")
    ])
    submit = SubmitField('Update Password')
    
class QuizForm(FlaskForm):
    assigned_class = SelectField('Assign to Class', choices=[
        ('Primary 1', 'Primary 1'), ('Primary 2', 'Primary 2'), ('Primary 3', 'Primary 3'),
        ('Primary 4', 'Primary 4'), ('Primary 5', 'Primary 5'), ('Primary 6', 'Primary 6'),
        ('JHS 1', 'JHS 1'), ('JHS 2', 'JHS 2'), ('JHS 3', 'JHS 3'),
        ('SHS 1', 'SHS 1'), ('SHS 2', 'SHS 2'), ('SHS 3', 'SHS 3')
    ], validators=[DataRequired()])
    course_id = HiddenField()
    course_name = SelectField('Subject/Course', choices=[], validators=[DataRequired()])
    title = StringField('Title', validators=[DataRequired()])
    start_datetime = DateTimeLocalField(
        'Start DateTime', format='%Y-%m-%dT%H:%M', validators=[DataRequired()]
    )
    end_datetime = DateTimeLocalField(
        'End DateTime', format='%Y-%m-%dT%H:%M', validators=[DataRequired()]
    )
    duration = SelectField(
        'Duration', 
        choices=[('15','15'),('30','30'),('45','45'),('60','60'),('90','90'),('120','120')]
    )
    attempts_allowed = IntegerField('Attempts Allowed', validators=[DataRequired(), NumberRange(min=1)])
    content_file = FileField('Upload File')
    submit = SubmitField('Save Quiz')

class ExamSetForm(FlaskForm):
    name = StringField("Set Name", validators=[DataRequired(), Length(max=50)])
    access_password = StringField('Set Password', validators=[DataRequired()])
    submit = SubmitField("Save")

class ExamForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    subject = StringField('Subject', validators=[DataRequired()])
    assigned_class = SelectField('Assign to Class', validators=[DataRequired()])
    start_datetime = DateTimeLocalField('Start', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_datetime = DateTimeLocalField('End', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    duration_minutes = IntegerField('Duration (minutes)')
    assignment_mode = SelectField('Assignment Mode', choices=[
        ('random', 'Admin: Random set'),
        ('hash', 'Deterministic: hash(student) → set'),
        ('choice', 'Student chooses set'),
    ], default='random')
    assignment_seed = StringField('Assignment seed (optional)')
    submit = SubmitField('Save')
    
class ExamOptionForm(FlaskForm):
    text = StringField("Option Text", validators=[DataRequired()])
    is_correct = BooleanField("Correct")

class ExamQuestionForm(FlaskForm):
    question_text = TextAreaField("Question", validators=[DataRequired()])
    question_type = SelectField(
        "Type",
        choices=[("mcq", "Multiple Choice"), ("true_false", "True/False"), ("subjective", "Subjective")],
        validators=[DataRequired()]
    )
    marks = IntegerField("Marks", validators=[DataRequired()])
    options = FieldList(FormField(ExamOptionForm), min_entries=2, max_entries=6)
    subjective_rubric = TextAreaField("Expected Answer / Rubric")  # <--- add this
    submit = SubmitField("Save")

class AssignmentForm(FlaskForm):
    assigned_class = SelectField('Assign to Class', choices=[
        ('Primary 1', 'Primary 1'), ('Primary 2', 'Primary 2'), ('Primary 3', 'Primary 3'),
        ('Primary 4', 'Primary 4'), ('Primary 5', 'Primary 5'), ('Primary 6', 'Primary 6'),
        ('JHS 1', 'JHS 1'), ('JHS 2', 'JHS 2'), ('JHS 3', 'JHS 3'),
        ('SHS 1', 'SHS 1'), ('SHS 2', 'SHS 2'), ('SHS 3', 'SHS 3')
    ], validators=[DataRequired()])

    course_id = HiddenField(validators=[DataRequired()])
    course_name = SelectField('Course', choices=[], validators=[DataRequired()])

    title = StringField('Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    instructions = TextAreaField('Instructions')
    due_date = DateTimeField('Due Date & Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    max_score = FloatField('Max Score', validators=[DataRequired()])
    file = FileField('Upload File', validators=[FileAllowed(['pdf','doc','docx','ppt','pptx','txt'])])
    submit = SubmitField('Submit')

class MaterialForm(FlaskForm):
    title = StringField('Material Title', validators=[DataRequired()])
    assigned_class = SelectField('Assigned Class', choices=[], validators=[DataRequired()])
    course_name = SelectField('Course Name', choices=[], validators=[DataRequired()])
    files = MultipleFileField('Files', validators=[DataRequired()])
    submit = SubmitField('Upload')


class CourseRegistrationForm(FlaskForm):
    semester = SelectField('Semester',
        choices=[('First','First'), ('Second','Second')],
        validators=[DataRequired()])
    
    academic_year = SelectField('Academic Year', validators=[DataRequired()])
    
    courses = SelectMultipleField('Optional Courses',
        coerce=int,
        validators=[])
    
    submit = SubmitField('Register Courses')
    
class CourseForm(FlaskForm):
    name           = StringField('Course Name', validators=[DataRequired()])
    code           = StringField('Course Code', validators=[DataRequired(), Length(max=20)])
    assigned_class = SelectField('Class', choices=get_class_choices(), validators=[DataRequired()])
    semester       = SelectField('Semester', choices=[('First','First'),('Second','Second')], validators=[DataRequired()])
    credit_hours = IntegerField('Credit Hours', validators=[DataRequired(), NumberRange(min=1, max=6)])
    academic_year  = StringField('Academic Year', validators=[DataRequired()])
    is_mandatory   = BooleanField('Mandatory?')
    submit         = SubmitField('Save Course')

class CourseLimitForm(FlaskForm):
    class_level     = SelectField('Class', choices=get_class_choices(), validators=[DataRequired()])
    semester        = SelectField('Semester', choices=[('First','First'),('Second','Second')], validators=[DataRequired()])
    academic_year   = StringField('Academic Year', validators=[DataRequired()])
    mandatory_limit = IntegerField('Mandatory Course Limit', validators=[DataRequired(), NumberRange(min=0)])
    optional_limit  = IntegerField('Optional Course Limit', validators=[DataRequired(), NumberRange(min=0)])
    submit          = SubmitField('Save Limits')

class MeetingForm(FlaskForm):
    title = StringField('Meeting Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    course_id = SelectField('Course', coerce=int, validators=[DataRequired()])
    scheduled_start = DateTimeLocalField('Start Date & Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    scheduled_end = DateTimeLocalField('End Date & Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    submit = SubmitField('Save Meeting')

class RecordingForm(FlaskForm):
    title = StringField('Recording Title', validators=[DataRequired()])
    file = FileField('Upload Recording', validators=[DataRequired()])
    submit = SubmitField('Upload Recording')
