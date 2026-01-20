from datetime import datetime
from functools import wraps
import os, random, string
from flask import (Blueprint, current_app, render_template, redirect, request, url_for, flash, session, make_response)
import pdfkit
from utils.email import send_email, send_application_completed_email, send_email_verification
from utils.security import verify_email_code
from flask_login import login_user
from flask_mail import Message
from werkzeug.utils import secure_filename
from PIL import Image
from utils.extensions import db
from .models import AdmissionVoucher, Applicant, Application, ApplicationResult
from .forms import (ApplicantRegistrationForm, ApplicantLoginForm, PersonalInfoForm, GuardianForm, ProgrammeChoiceForm, EducationForm, ExamInfoForm, ExamResultForm, PassportUploadForm, DeclarationForm, PurchaseVoucherForm, VoucherAuthenticationForm)
from datetime import datetime, timedelta

# =====================================================
# Blueprint
# =====================================================
admissions_bp = Blueprint('admissions', __name__, template_folder='templates', static_folder='static', url_prefix='/admissions')

PDFKIT_CONFIG = pdfkit.configuration(
    wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
)

# =====================================================
# Applicant login required decorator
# =====================================================
def applicant_login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if 'applicant_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('admissions.login'))
        return view(*args, **kwargs)
    return wrapped_view


# helper to pick next step for a partially completed application
def get_next_application_step(application):
    """
    Returns a string route like 'admissions.personal_info', 'admissions.guardian', ...
    If the application is complete (or none), returns 'admissions.preview' or None.
    """
    if not application:
        return 'admissions.personal_info'

    # STEP 1: Personal info required fields
    required_personal = (
        application.surname,
        application.other_names,
        application.gender,
        application.dob,
        application.nationality,
        application.phone,
        application.email
    )
    if not all(required_personal):
        return 'admissions.personal_info'

    # STEP 2: Guardian
    if not application.guardian_name:
        return 'admissions.guardian'

    # STEP 3: Programme choices
    if not application.first_choice:
        return 'admissions.programme'

    # STEP 4: Education history - depends on your data model; assume some fields
    if not application.documents:  # or check explicit fields if you saved schools
        # if you track education entries in another model, check those here
        return 'admissions.education'

    # STEP 5-6: Exams & results - check ApplicationResult entries
    results_count = ApplicationResult.query.filter_by(application_id=application.id).count()
    if results_count == 0:
        return 'admissions.exam_results'

    # STEP 7: Passport / photo - check ApplicationDocument (type='photo') or session info
    has_photo = any(d.document_type == 'photo' and d.file_path for d in application.documents)
    if not has_photo:
        return 'admissions.passport_upload'

    # if everything present but status is still draft, go to preview
    if application.status != 'submitted':
        return 'admissions.preview'

    # already submitted
    return None

# =====================================================
# Landing Page
# =====================================================
@admissions_bp.route('/')
def index():
    return render_template('admissions/apply.html')


# =====================================================
# Registration
# =====================================================
@admissions_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')

        if not email or not password or not phone:
            flash('Please fill all required fields.', 'danger')
            return redirect(url_for('admissions.register'))

        if Applicant.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'warning')
            return redirect(url_for('admissions.login'))

        # Create applicant
        applicant = Applicant(email=email, phone=phone)
        applicant.set_password(password)

        # Generate verification code
        verification_code = str(random.randint(100000, 999999))
        applicant.email_verification_code = verification_code
        applicant.email_verification_expires = datetime.utcnow() + timedelta(minutes=15)
        applicant.is_email_verified = False

        db.session.add(applicant)
        db.session.commit()

        # Store email for verification step
        session['pending_email'] = email

        # Send verification email
        send_email_verification(applicant, verification_code)

        flash('Account created. Please verify your email to continue.', 'info')
        return redirect(url_for('admissions.verify_email'))

    return render_template('admissions/register.html')

@admissions_bp.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    applicant = Applicant.query.filter_by(email=session.get('pending_email')).first()

    if not applicant:
        flash("No pending email found to verify.", "warning")
        return redirect(url_for('admissions.login'))

    if request.method == 'POST':
        code_entered = request.form.get('code', '').strip()
        success, message = verify_email_code(applicant, code_entered)

        if success:
            login_user(applicant)
            flash("Email verified successfully!", "success")
            # Redirect to voucher authentication page
            return redirect(url_for('admissions.voucher_authentication'))

        flash(message, "danger")

    return render_template('admissions/verify_email.html')

@admissions_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    user_email = session.get('pending_verification_email')
    if not user_email:
        flash("No email to verify.", "warning")
        return redirect(url_for('admissions.login'))

    # logic to generate and send verification code here
    flash("Verification code resent. Please check your email.", "success")
    return redirect(url_for('admissions.verify_email'))

# =====================================================
# Login
# =====================================================
@admissions_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = ApplicantLoginForm()

    if form.validate_on_submit():
        applicant = Applicant.query.filter_by(email=form.email.data).first()

        if applicant and applicant.check_password(form.password.data):
            session.clear()
            session['applicant_id'] = applicant.id

            # If applicant already has an application in progress, continue it
            application = Application.query.filter_by(applicant_id=applicant.id).first()
            if application and application.status != 'submitted':
                next_route = get_next_application_step(application)
                if next_route:
                    return redirect(url_for(next_route))

            # otherwise go to voucher auth (if you want them to re-verify) or dashboard
            return redirect(url_for('admissions.voucher_authentication'))

        flash('Invalid email or password.', 'danger')

    return render_template('admissions/login.html', form=form)

@admissions_bp.route('/voucher-authentication', methods=['GET', 'POST'])
def voucher_authentication():
    # require login (since voucher usage is bound to applicant)
    applicant_id = session.get('applicant_id')
    if not applicant_id:
        flash('Please login to authenticate a voucher.', 'warning')
        return redirect(url_for('admissions.login'))

    form = VoucherAuthenticationForm()

    if form.validate_on_submit():
        pin = form.voucher_pin.data.strip()
        serial = form.serial_number.data.strip()

        voucher = AdmissionVoucher.query.filter_by(pin=pin, serial=serial).first()
        if not voucher:
            flash("Invalid voucher PIN or Serial Number.", "danger")
            return redirect(url_for('admissions.voucher_authentication'))

        # expired?
        if voucher.valid_until and voucher.valid_until < datetime.utcnow():
            flash("This voucher has expired.", "warning")
            return redirect(url_for('admissions.voucher_authentication'))

        # If voucher has already been used...
        if voucher.is_used:
            if voucher.used_by == applicant_id:
                # good — this user already used it, let them continue
                flash("Voucher already used by you — resuming your application.", "info")
                # ensure the applicant has an Application row
                app_row = Application.query.filter_by(applicant_id=applicant_id).first()
                if not app_row:
                    # create application row if missing
                    app_row = Application(applicant_id=applicant_id, status='draft')
                    db.session.add(app_row)
                    db.session.commit()

                next_route = get_next_application_step(app_row) or 'admissions.dashboard'
                return redirect(url_for(next_route))
            else:
                # used by someone else
                flash("This voucher has already been used by another applicant.", "warning")
                return redirect(url_for('admissions.voucher_authentication'))

        # At this point voucher is unused and valid -> bind it
        voucher.mark_as_used(applicant_id)
        db.session.commit()

        # ensure applicant has an application row
        app_row = Application.query.filter_by(applicant_id=applicant_id).first()
        if not app_row:
            app_row = Application(applicant_id=applicant_id, status='draft')
            db.session.add(app_row)
            db.session.commit()

        flash("Voucher successfully authenticated! You may continue your application.", "success")
        next_route = get_next_application_step(app_row) or 'admissions.dashboard'
        return redirect(url_for(next_route))

    # When rendering the page, we can pass the user's own vouchers to optionally display them
    # (optional, useful so they can see the voucher assigned to them)
    user_vouchers = AdmissionVoucher.query.filter_by(purchaser_email=Applicant.query.get(applicant_id).email).order_by(AdmissionVoucher.created_at.desc()).all() if applicant_id else []
    return render_template('admissions/voucher_authentication.html', form=form, vouchers=user_vouchers)

@admissions_bp.route('/voucher/validate', methods=['GET', 'POST'])
def voucher_validate():
    if 'applicant_id' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('admissions.login'))

    if request.method == 'POST':
        pin = request.form.get('pin')
        serial = request.form.get('serial')

        voucher = AdmissionVoucher.query.filter_by(pin=pin, serial=serial).first()
        if not voucher:
            flash('Invalid voucher credentials.', 'danger')
            return redirect(url_for('admissions.voucher_validate'))

        if voucher.is_used:
            flash('Voucher already used.', 'warning')
            return redirect(url_for('admissions.voucher_validate'))

        # Bind to applicant and mark used
        voucher.mark_as_used(session['applicant_id'])
        db.session.commit()
        flash('Voucher validated — you may now start your application.', 'success')
        return redirect(url_for('admissions.start_application'))

    return render_template('admissions/voucher_validate.html')


@admissions_bp.route('/purchase-voucher', methods=['GET', 'POST'])
def purchase_voucher():
    form = PurchaseVoucherForm()

    if form.validate_on_submit():
        full_name = form.full_name.data
        email = form.email.data
        phone = form.phone.data
        amount = form.amount.data

        # ============================
        # Simulate payment gateway
        # ============================
        payment_success = True  # Replace with real payment integration

        if payment_success:
            # 1️⃣ Try to fetch an unused voucher first
            voucher = AdmissionVoucher.query.filter_by(
                is_used=False,
                purchaser_email=None  # only take truly unassigned vouchers
            ).order_by(AdmissionVoucher.created_at.asc()).first()

            if voucher:
                # Use pre-generated voucher
                voucher.amount = amount  # update amount if needed
                voucher.purchaser_email = email
                pin = voucher.pin
                serial = voucher.serial
            else:
                # 2️⃣ Generate a new voucher
                pin = ''.join(random.choices(string.digits, k=8))
                serial = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

                voucher = AdmissionVoucher(
                    pin=pin,
                    serial=serial,
                    amount=amount,
                    purchaser_email=email,
                    valid_until=datetime.utcnow() + timedelta(days=180),
                    is_used=False
                )
                db.session.add(voucher)

            # 3️⃣ Commit voucher to DB
            db.session.commit()

            # ============================
            # Send voucher email
            # ============================
            body = f"""
Hello {full_name},

Thank you for your payment of GHS {amount}.
Your voucher details are as follows:

PIN: {pin}
Serial Number: {serial}

Please keep this information safe. You will need it to access the application form.

Best regards,
Admissions Office
"""
            email_sent = send_email(to_email=email, subject="Your Admission Voucher Details", body=body)

            if not email_sent:
                flash(f"Voucher assigned, but failed to send email to {email}.", "warning")
            else:
                flash(f"Payment successful! Your voucher PIN and Serial Number have been sent to {email}.", "success")

            return redirect(url_for('admissions.voucher_authentication'))

        else:
            flash("Payment failed. Please try again.", "danger")
            return redirect(url_for('admissions.purchase_voucher'))

    return render_template('admissions/purchase_voucher.html', form=form)

# =====================================================
# Dashboard
# =====================================================
@admissions_bp.route('/dashboard')
@applicant_login_required
def dashboard():
    applicant = Applicant.query.get(session['applicant_id'])
    return render_template('admissions/dashboard.html', applicant=applicant)


# =====================================================
# Start Application
# =====================================================
@admissions_bp.route('/start-application')
@applicant_login_required
def start_application():
    applicant = Applicant.query.get(session['applicant_id'])

    if applicant.application:
        flash('You already have an active application.', 'info')
        return redirect(url_for('admissions.dashboard'))

    application = Application(
        applicant_id=applicant.id,
        status='draft'
    )

    db.session.add(application)
    db.session.commit()

    return redirect(url_for('admissions.personal_info'))


# =====================================================
# STEP 1: Personal Information
# =====================================================
@admissions_bp.route('/application/personal-info', methods=['GET', 'POST'])
@applicant_login_required
def personal_info():
    form = PersonalInfoForm()
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()

    if not application:
        # Create application if it doesn't exist
        application = Application(applicant_id=session['applicant_id'])
        db.session.add(application)
        db.session.commit()

    if form.validate_on_submit():
        # Save form data to database
        application.title = form.title.data
        application.surname = form.surname.data
        application.other_names = form.other_names.data
        application.gender = form.gender.data
        application.dob = form.dob.data
        application.nationality = form.nationality.data
        application.marital_status = form.marital_status.data
        application.home_region = form.home_region.data
        application.phone = form.phone.data
        application.email = form.email.data
        application.postal_address = form.postal_address.data

        db.session.commit()
        return redirect(url_for('admissions.guardian'))

    # Pre-fill form if data exists
    if application:
        form.title.data = application.title
        form.surname.data = application.surname
        form.other_names.data = application.other_names
        form.gender.data = application.gender
        form.dob.data = application.dob
        form.nationality.data = application.nationality
        form.marital_status.data = application.marital_status
        form.home_region.data = application.home_region
        form.phone.data = application.phone
        form.email.data = application.email
        form.postal_address.data = application.postal_address

    # Pass form errors to template
    return render_template(
        'admissions/personal_info.html',
        form=form,
        errors=form.errors
    )


# =====================================================
# STEP 2: Guardian Information
# =====================================================
@admissions_bp.route('/application/guardian', methods=['GET', 'POST'])
@applicant_login_required
def guardian():
    form = GuardianForm()
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()

    if form.validate_on_submit():
        application.guardian_name = form.name.data
        application.guardian_relation = form.relation.data
        application.guardian_occupation = form.occupation.data
        application.guardian_phone = form.phone.data
        application.guardian_email = form.email.data
        application.guardian_address = form.address.data

        db.session.commit()
        return redirect(url_for('admissions.programme'))

    if application:
        form.name.data = application.guardian_name
        form.relation.data = application.guardian_relation
        form.occupation.data = application.guardian_occupation
        form.phone.data = application.guardian_phone
        form.email.data = application.guardian_email
        form.address.data = application.guardian_address

    return render_template('admissions/guardian.html', form=form)


# =====================================================
# STEP 3: Programme Choice
# =====================================================
@admissions_bp.route('/application/programme', methods=['GET', 'POST'])
@applicant_login_required
def programme():
    form = ProgrammeChoiceForm()
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()

    if form.validate_on_submit():
        application.first_choice = form.first_choice.data
        application.first_stream = form.first_stream.data
        application.second_choice = form.second_choice.data
        application.second_stream = form.second_stream.data
        application.third_choice = form.third_choice.data
        application.third_stream = form.third_stream.data
        application.fourth_choice = form.fourth_choice.data
        application.fourth_stream = form.fourth_stream.data

        db.session.commit()
        return redirect(url_for('admissions.education'))

    if application:
        form.first_choice.data = application.first_choice
        form.first_stream.data = application.first_stream
        form.second_choice.data = application.second_choice
        form.second_stream.data = application.second_stream
        form.third_choice.data = application.third_choice
        form.third_stream.data = application.third_stream
        form.fourth_choice.data = application.fourth_choice
        form.fourth_stream.data = application.fourth_stream

    return render_template('admissions/programme.html', form=form)


# =====================================================
# STEP 4: Education History
# =====================================================
@admissions_bp.route('/application/education', methods=['GET', 'POST'])
@applicant_login_required
def education():
    form = EducationForm()

    if form.validate_on_submit():
        return redirect(url_for('admissions.exam_info'))

    return render_template('admissions/education.html', form=form)


# =====================================================
# STEP 5: Exam Information
# =====================================================
@admissions_bp.route('/application/exam-info', methods=['GET', 'POST'])
@applicant_login_required
def exam_info():
    form = ExamInfoForm()

    if form.validate_on_submit():
        return redirect(url_for('admissions.exam_results'))

    return render_template('admissions/exam_info.html', form=form)


# =====================================================
# STEP 6: Exam Results
# =====================================================
@admissions_bp.route('/application/exam-results', methods=['GET', 'POST'])
@applicant_login_required
def exam_results():
    form = ExamResultForm()
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()

    if request.method == 'POST':
        # Get all subjects and grades from the form
        subjects = request.form.getlist('subject[]')
        grades = request.form.getlist('grade[]')

        # Basic validation: ensure lists match
        if len(subjects) != len(grades):
            flash('Mismatch in subjects and grades.', 'danger')
            return redirect(url_for('admissions.exam_results'))

        # Clear existing results for this applicant (optional)
        ApplicationResult.query.filter_by(application_id=application.id).delete()

        # Save new results
        for subj, grd in zip(subjects, grades):
            result = ApplicationResult(
                application_id=application.id,
                subject=subj,
                grade=grd
            )
            db.session.add(result)

        db.session.commit()
        flash('Exam results saved successfully.', 'success')
        return redirect(url_for('admissions.passport_upload'))

    return render_template('admissions/exam_results.html', form=form, application=application)


from PIL import Image
from werkzeug.utils import secure_filename

from PIL import Image
from werkzeug.utils import secure_filename
import colorsys
import os

@admissions_bp.route('/application/passport', methods=['GET', 'POST'])
@applicant_login_required
def passport_upload():
    form = PassportUploadForm()
    error = None
    applicant_id = session['applicant_id']

    # Directory where uploaded images are stored
    upload_dir = os.path.join(
        current_app.root_path,
        'admissions', 'static', 'uploads',
        str(applicant_id)
    )
    os.makedirs(upload_dir, exist_ok=True)

    # Check for existing passport image in folder
    existing_files = [f for f in os.listdir(upload_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    existing_passport = existing_files[0] if existing_files else None

    if form.validate_on_submit():
        passport = form.passport.data
        filename = secure_filename(passport.filename)
        temp_path = os.path.join(upload_dir, 'temp_' + filename)
        passport.save(temp_path)

        try:
            img = Image.open(temp_path)
            img = img.convert('RGB')
            width, height = img.size

            if width == 0 or height == 0:
                raise ValueError("Uploaded image is empty")

            # Sample pixels at 5x5 grid
            sample_points = [(min(int(width*i/4), width-1), min(int(height*j/4), height-1))
                             for i in range(5) for j in range(5)]

            def is_green_pixel(rgb):
                r, g, b = rgb
                h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                return 0.23 <= h <= 0.42 and s >= 0.3 and v >= 0.3

            green_count = sum(1 for px in sample_points if is_green_pixel(img.getpixel(px)))
            if green_count / len(sample_points) >= 0.6:
                final_path = os.path.join(upload_dir, filename)
                os.rename(temp_path, final_path)
                session['uploaded_passport'] = filename
                existing_passport = filename
                return redirect(url_for('admissions.preview'))
            else:
                error = "Passport photo must have a green background."
                os.remove(temp_path)

        except Exception as e:
            error = f"Error processing image: {str(e)}"
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return render_template(
        'admissions/passport.html',
        form=form,
        error=error,
        existing_passport=existing_passport
    )


# =====================================================
# STEP 8: Preview
# =====================================================
@admissions_bp.route('/application/preview')
@applicant_login_required
def preview():
    application = Application.query.filter_by(
        applicant_id=session['applicant_id']
    ).first()

    return render_template(
        'admissions/application_preview.html',
        application=application
    )


# =====================================================
# STEP 9: Declaration & Submit
# =====================================================
@admissions_bp.route('/application/declaration', methods=['GET', 'POST'])
@applicant_login_required
def declaration():
    form = DeclarationForm()
    application = Application.query.filter_by(
        applicant_id=session['applicant_id']
    ).first()

    if form.validate_on_submit():
        application.status = 'submitted'
        application.submitted_at = datetime.utcnow()
        db.session.commit()

        # Send completion email
        send_application_completed_email(application.applicant)

        flash("Application submitted successfully!", "success")
        return redirect(url_for('admissions.application_success'))

    return render_template('admissions/declaration.html', form=form)


# =====================================================
# Application Step Redirector
# =====================================================
@admissions_bp.route('/application/step/<int:step>')
@applicant_login_required
def application_step(step):
    routes = {
        1: 'admissions.personal_info',
        2: 'admissions.guardian',
        3: 'admissions.programme',
        4: 'admissions.education',
        5: 'admissions.exam_info',
        6: 'admissions.exam_results',
        7: 'admissions.passport_upload',
    }

    route = routes.get(step)
    if route:
        return redirect(url_for(route))
    flash('Invalid application step.', 'danger')
    return redirect(url_for('admissions.preview'))


@admissions_bp.route('/application/success')
@applicant_login_required
def application_success():
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()
    if not application or application.status != 'submitted':
        flash("You have not submitted an application yet.", "warning")
        return redirect(url_for('admissions.dashboard'))

    return render_template('admissions/application_success.html', application=application)

# =====================================================
# Download Application PDF
@admissions_bp.route('/application/download-pdf')
@applicant_login_required
def download_application_pdf():
    application = Application.query.filter_by(applicant_id=session['applicant_id']).first()
    if not application:
        flash("No application found to download.", "warning")
        return redirect(url_for('admissions.dashboard'))

    # Render HTML template for PDF
    html = render_template('admissions/application_pdf.html', application=application)

    try:
        # Generate PDF
        pdf = pdfkit.from_string(html, False, configuration=PDFKIT_CONFIG, options={
            'enable-local-file-access': None,  # allow local images/css
            'page-size': 'A4',
            'margin-top': '10mm',
            'margin-bottom': '10mm',
            'margin-left': '10mm',
            'margin-right': '10mm',
            'encoding': "UTF-8"
        })

        # Return as downloadable response
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=application_{application.id}.pdf'
        return response

    except Exception as e:
        flash(f"Failed to generate PDF: {str(e)}", "danger")
        return redirect(url_for('admissions.dashboard'))


# =====================================================
# Logout
# =====================================================
@admissions_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admissions.login'))
