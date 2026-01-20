from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, IntegerField, StringField, PasswordField, SubmitField, DateField, SelectField, FileField, FloatField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, NumberRange

# ==============================
# 1️⃣ Registration Form
# ==============================
class ApplicantRegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(min=10, max=15)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')


# ==============================
# 2️⃣ Login Form
# ==============================
class ApplicantLoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class PersonalInfoForm(FlaskForm):
    title = SelectField(
        'Title',
        choices=[('Miss', 'Miss'), ('Mr', 'Mr'), ('Mrs', 'Mrs')],
        validators=[DataRequired()]
    )

    surname = StringField('Surname', validators=[DataRequired()])
    other_names = StringField('Other / Middle Names', validators=[DataRequired()])

    gender = SelectField(
        'Gender',
        choices=[('Female', 'Female'), ('Male', 'Male')],
        validators=[DataRequired()]
    )

    dob = DateField('Date of Birth', format='%Y-%m-%d', validators=[DataRequired()])

    nationality = StringField('Nationality', validators=[DataRequired()])  # <- ADD THIS

    marital_status = SelectField(
        'Marital Status',
        choices=[('Single', 'Single'), ('Married', 'Married')],
        validators=[DataRequired()]
    )

    home_region = SelectField(
        'Home Region',
        choices=[
            ('Greater Accra', 'Greater Accra'),
            ('Ashanti', 'Ashanti'),
            ('Central', 'Central'),
            ('Eastern', 'Eastern'),
            ('Volta', 'Volta'),
            ('Western', 'Western'),
            ('Northern', 'Northern'),
            ('Upper East', 'Upper East'),
            ('Upper West', 'Upper West'),
            ('Bono', 'Bono'),
            ('Ahafo', 'Ahafo'),
            ('Oti', 'Oti'),
            ('Savannah', 'Savannah'),
            ('North East', 'North East')
        ],
        validators=[DataRequired()]
    )

    phone = StringField('Phone Number', validators=[DataRequired(), Length(min=10)])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    postal_address = TextAreaField('Postal Address', validators=[DataRequired()])

    submit = SubmitField('Save & Continue')


class GuardianForm(FlaskForm):
    name = StringField('Guardian Name', validators=[DataRequired()])
    relation = StringField('Relation to Applicant', validators=[DataRequired()])
    occupation = StringField('Occupation', validators=[DataRequired()])
    phone = StringField('Phone Number', validators=[DataRequired()])
    email = StringField('Email Address', validators=[Optional(), Email()])
    address = TextAreaField('Residential Address', validators=[DataRequired()])

    submit = SubmitField('Save & Continue')


# Hardcoded sample programmes
PROGRAMME_CHOICES = [
    ('BSc Computer Science', 'BSc Computer Science'),
    ('BSc Mathematics', 'BSc Mathematics'),
    ('BSc Physics', 'BSc Physics'),
    ('BA Economics', 'BA Economics'),
    ('BSc Biology', 'BSc Biology'),
]

class ProgrammeChoiceForm(FlaskForm):
    first_choice = SelectField(
        'First Choice Programme', 
        choices=PROGRAMME_CHOICES, 
        validators=[DataRequired()]
    )
    first_stream = SelectField(
        'Stream',
        choices=[('Regular', 'Regular'), ('Fee Paying', 'Fee Paying')]
    )

    second_choice = SelectField(
        'Second Choice Programme', 
        choices=PROGRAMME_CHOICES, 
        validators=[Optional()]
    )
    second_stream = SelectField(
        'Stream',
        choices=[('Regular', 'Regular'), ('Fee Paying', 'Fee Paying')],
        validators=[Optional()]
    )

    third_choice = SelectField(
        'Third Choice Programme', 
        choices=PROGRAMME_CHOICES, 
        validators=[Optional()]
    )
    third_stream = SelectField(
        'Stream',
        choices=[('Regular', 'Regular'), ('Fee Paying', 'Fee Paying')],
        validators=[Optional()]
    )

    fourth_choice = SelectField(
        'Fourth Choice Programme', 
        choices=PROGRAMME_CHOICES, 
        validators=[Optional()]
    )
    fourth_stream = SelectField(
        'Stream',
        choices=[('Regular', 'Regular'), ('Fee Paying', 'Fee Paying')],
        validators=[Optional()]
    )

    submit = SubmitField('Save & Continue')
    

class EducationForm(FlaskForm):
    institution = StringField('Institution Attended', validators=[DataRequired()])
    programme = StringField('Programme Pursued', validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])

    submit = SubmitField('Save & Continue')


class ExamInfoForm(FlaskForm):
    exam_type = SelectField(
        'Exam Type',
        choices=[('WASSCE', 'WASSCE (Ghanaian)'), ('SSSCE', 'SSSCE')],
        validators=[DataRequired()]
    )

    sitting = SelectField(
        'Sitting',
        choices=[('May/June', 'May/June (School)'), ('Nov/Dec', 'Nov/Dec (Private)')],
        validators=[DataRequired()]
    )

    exam_year = StringField('Exam Year', validators=[DataRequired()])
    index_number = StringField('Index Number', validators=[DataRequired()])

    submit = SubmitField('Save & Continue')


class ExamResultForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired()])
    grade = SelectField(
        'Grade',
        choices=[
            ('A1', 'A1'), ('B2', 'B2'), ('B3', 'B3'),
            ('C4', 'C4'), ('C5', 'C5'), ('C6', 'C6'),
            ('D7', 'D7'), ('E8', 'E8'), ('F9', 'F9')
        ],
        validators=[DataRequired()]
    )

    submit = SubmitField('Add Result')


class PassportUploadForm(FlaskForm):
    passport = FileField(
        'Upload Passport Photograph',
        validators=[DataRequired()]
    )
    submit = SubmitField('Upload & Continue')


class DeclarationForm(FlaskForm):
    accept_terms = BooleanField('I declare that all information provided is true and complete', validators=[DataRequired(message="You must accept the declaration.")])
    agree_policy = BooleanField('I agree to abide by the institution’s policies', validators=[DataRequired(message="You must agree to the policies.")])
    submit = SubmitField('Submit Application')
    
class VoucherAuthenticationForm(FlaskForm):
    voucher_pin = StringField('Voucher PIN', validators=[DataRequired(), Length(min=6, max=20)])
    serial_number = StringField('Serial Number', validators=[DataRequired(), Length(min=6, max=20)])
    submit = SubmitField('Authenticate Voucher')

class PurchaseVoucherForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired()])
    email = EmailField('Email Address', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[DataRequired()])
    amount = IntegerField('Amount (GHS)', validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Proceed to Payment')