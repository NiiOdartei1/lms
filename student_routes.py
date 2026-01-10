from flask import Blueprint, current_app, render_template, abort, redirect, url_for, flash, jsonify, session, send_from_directory, send_file, make_response
import json, os
from flask import request
from flask_login import login_required, current_user, login_user
from sqlalchemy import func
from werkzeug.utils import safe_join, secure_filename
from models import ExamTimetableEntry, TeacherAssessment, TeacherAssessmentAnswer, TeacherAssessmentPeriod, TeacherAssessmentQuestion, TeacherCourseAssignment, TeacherProfile, User, Quiz, StudentQuizSubmission, Question, StudentProfile, QuizAttempt, Assignment, CourseMaterial, StudentCourseRegistration, Course,  TimetableEntry, AcademicCalendar, AcademicYear, AppointmentSlot, AppointmentBooking, StudentFeeBalance, ClassFeeStructure, StudentFeeTransaction, Exam, ExamSubmission, ExamQuestion, ExamAttempt, ExamSet, ExamSetQuestion, Notification, NotificationRecipient, Meeting, StudentAnswer
from datetime import datetime, timedelta
from forms import CourseRegistrationForm, ChangePasswordForm, StudentLoginForm
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image as RLImage
import io
from reportlab.lib.utils import ImageReader
import qrcode
from PIL import Image, ImageDraw
import textwrap
from utils.extensions import db
from utils.result_builder import ResultBuilder
from utils.results_manager import ResultManager
from utils.result_templates import get_template_path

student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.route('/login', methods=['GET', 'POST'])
def student_login():
    form = StudentLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        user = User.query.filter_by(user_id=user_id, role='student').first()
        if user and user.username.lower() == username.lower() and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for('student.dashboard'))
        flash("Invalid student credentials.", "danger")

    return render_template('student/login.html', form=form)

@student_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student':
        abort(403)
    return render_template('student/dashboard.html', user=current_user)


@student_bp.app_context_processor
def inject_notification_count():
    unread_count = 0
    if current_user.is_authenticated:
        from models import NotificationRecipient

        if hasattr(current_user, "user_id"):  
            # Regular User (student, teacher, parent)
            unread_count = NotificationRecipient.query.filter_by(
                user_id=current_user.user_id,
                is_read=False
            ).count()

        elif hasattr(current_user, "admin_id"):  
            # Admin → get all unread notifications
            unread_count = NotificationRecipient.query.filter_by(is_read=False).count()

    return dict(unread_count=unread_count)


@student_bp.route('/courses', methods=['GET', 'POST'])
@login_required
def register_courses():
    form = CourseRegistrationForm()
    student = current_user
    now = datetime.utcnow()
    start, registration_deadline = Course.get_registration_window()

    profile = StudentProfile.query.filter_by(user_id=student.user_id).first()
    if not profile:
        flash("Student profile not found.", "danger")
        return redirect(url_for("student.dashboard"))

    class_name = profile.current_class

    # ✅ FIXED: use db directly
    years = (
        db.session.query(Course.academic_year)
        .distinct()
        .order_by(Course.academic_year)
        .all()
    )

    if not years:
        flash("No academic years available yet. Contact admin.", "warning")
        return redirect(url_for("student.dashboard"))

    form.academic_year.choices = [(y[0], y[0]) for y in years]

    # Determine current step
    step = request.form.get("step")
    selected_sem = request.form.get("semester") or form.semester.data or "First"
    selected_year = request.form.get("academic_year") or form.academic_year.data or years[-1][0]

    form.semester.data = selected_sem
    form.academic_year.data = selected_year

    courses = Course.query.filter_by(
        assigned_class=class_name,
        semester=selected_sem,
        academic_year=selected_year
    ).all()

    mandatory_courses = [c for c in courses if c.is_mandatory]
    optional_courses = [c for c in courses if not c.is_mandatory]

    form.courses.choices = [(c.id, f"{c.code} - {c.name}") for c in optional_courses]

    registered = StudentCourseRegistration.query.filter_by(
        student_id=student.id,
        semester=selected_sem,
        academic_year=selected_year
    ).all()

    form.courses.data = [
        r.course_id for r in registered if not r.course.is_mandatory
    ]

    deadline_passed = registration_deadline and now > registration_deadline

    if request.method == "POST" and step == "register_courses" and form.validate_on_submit():
        if deadline_passed:
            flash("Registration deadline has passed.", "danger")
            return redirect(url_for("student.register_courses"))

        selected_ids = set(map(int, request.form.getlist("courses[]")))
        mandatory_ids = {c.id for c in mandatory_courses}
        final_course_ids = selected_ids | mandatory_ids

        StudentCourseRegistration.query.filter_by(
            student_id=student.id,
            semester=selected_sem,
            academic_year=selected_year
        ).delete()

        for cid in final_course_ids:
            db.session.add(
                StudentCourseRegistration(
                    student_id=student.id,
                    course_id=cid,
                    semester=selected_sem,
                    academic_year=selected_year
                )
            )

        db.session.commit()

        flash("Courses registered successfully!", "success")
        return redirect(url_for("student.register_courses"))

    show_courses = (step == "select_semester") or len(registered) > 0

    return render_template(
        "student/courses.html",
        form=form,
        mandatory_courses=mandatory_courses,
        optional_courses=optional_courses,
        registered_courses=registered,
        show_courses=show_courses,
        registration_deadline=registration_deadline,
        deadline_passed=deadline_passed
    )
    
@student_bp.route('/courses/reset', methods=['POST'])
@login_required
def reset_registration():
    student = current_user

    semester = request.form.get("semester")
    year = request.form.get("academic_year")

    if not semester or not year:
        flash("Semester or Academic Year missing for reset.", "danger")
        return redirect(url_for("student.register_courses"))

    # Delete the current registration
    StudentCourseRegistration.query.filter_by(
        student_id=student.id,
        semester=semester,
        academic_year=year
    ).delete()
    db.session.commit()

    flash("Course registration has been reset. You may register again.", "info")
    return redirect(url_for("student.register_courses"))

@student_bp.route('/my_results')
@login_required
def my_results():
    data = ResultBuilder.semester(current_user.id)

    if not data["released"]:
        return render_template("student/results_not_released.html")

    return render_template(
        "student/results.html",
        results=data["results"],
        academic_year=data["academic_year"],
        semester=data["semester"]
    )



# View results as HTML
@student_bp.route("/results/view/<student_id>")
def view_results(student_id):
    from utils.result_render import ResultRenderer

    data = ResultBuilder.semester(student_id)
    return ResultRenderer.render_html(data)

# Download results as PDF
from utils.result_render import render_pdf as render_results_pdf

@student_bp.route("/results/pdf/<student_id>")
@login_required
def download_result(student_id):
    data = ResultBuilder.semester(student_id)
    if not data["released"]:
        abort(403, "Results not released yet")
    return render_results_pdf({
        "student_id": student_id,
        "results": data["results"],
        "academic_year": data["academic_year"],
        "semester": data["semester"]
    })

@student_bp.route("/student/results")
@login_required
def semester_results():
    data = ResultBuilder.semester(current_user.id)

    if not data["released"]:
        return render_template(
            "student/results_not_released.html"
        )

    return render_template(
        "student/results.html",
        results=data["results"],
        academic_year=data["academic_year"],
        semester=data["semester"]
    )

from services.result_builder import ResultBuilder

@student_bp.route("/student/transcript")
@login_required
def transcript():
    data = ResultBuilder.transcript(current_user.id)

    return render_template(
        "student/transcript.html",
        transcript=data["records"],
        overall_gpa=data["overall_gpa"]
    )

@student_bp.route('/download_registered_courses_pdf')
@login_required
def download_registered_courses_pdf():
    student = current_user
    semester = request.args.get('semester')
    academic_year = request.args.get('academic_year')

    if not semester or not academic_year:
        abort(400, "Missing semester or academic year")

    # Fetch all registrations for student for that semester and year
    registrations = StudentCourseRegistration.query \
        .filter_by(
            student_id=student.id,
            semester=semester,
            academic_year=academic_year
        ) \
        .options(joinedload(StudentCourseRegistration.course)) \
        .all()

    if not registrations:
        abort(404, description="No registered courses found.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=60, bottomMargin=40)
    elements = []

    styles = getSampleStyleSheet()
    styleH = styles['Heading1']
    styleN = styles['Normal']

    # Title
    elements.append(Paragraph("Course Registration Summary", styleH))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Student Name: {student.full_name}", styleN))
    elements.append(Paragraph(f"Academic Year: {academic_year}", styleN))
    elements.append(Paragraph(f"Semester: {semester}", styleN))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", styleN))
    elements.append(Spacer(1, 24))

    # Table content
    data = [["Course Code", "Course Name", "Type"]]

    for reg in registrations:
        course = reg.course
        course_type = "Mandatory" if course.is_mandatory else "Optional"
        data.append([course.code, course.name, course_type])

    table = Table(data, colWidths=[100, 300, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#004085")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Course_Registration_{academic_year}_{semester}.pdf'
    return response

from datetime import datetime
from flask import render_template, abort
from flask_login import login_required, current_user
from math import ceil

@student_bp.route('/timetable')
@login_required
def view_timetable():
    if current_user.role != 'student':
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()
    entries = (
        TimetableEntry.query
        .filter_by(assigned_class=profile.current_class)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time)
        .all()
    )

    # === CUSTOM TIME SLOTS (mix of hours and partials) ===
    TIME_SLOTS = [
        (8*60, 9*60),
        (9*60, 10*60),
        (10*60, 10*60+30),
        (10*60+30, 11*60+30),
        (11*60+30, 12*60+30),
        (12*60+30, 13*60),
        (13*60, 14*60),
        (14*60, 15*60),
        (15*60, 16*60),
        (16*60, 17*60),
    ]

    # Build header ticks with widths (percent)
    MIN_START = TIME_SLOTS[0][0]
    MAX_END   = TIME_SLOTS[-1][1]
    total_minutes = MAX_END - MIN_START

    time_ticks = []
    for start, end in TIME_SLOTS:
        width_pct = ((end - start) / total_minutes) * 100.0
        label = f"{(start//60) % 12 or 12}:{start%60:02d} - {(end//60) % 12 or 12}:{end%60:02d}"
        time_ticks.append({
            'start': start,
            'end': end,
            'label': label,
            'width_pct': round(width_pct, 4)
        })

    # Build a list of vertical line positions (cumulative)
    cum = MIN_START
    vlines = []
    for start, end in TIME_SLOTS:
        cum += (end - start)
        cum_pct = ((cum - MIN_START) / total_minutes) * 100.0
        # determine whether this is a full-hour boundary (end minute = 0)
        is_thick = ((end % 60) == 0)
        vlines.append({'left_pct': round(cum_pct, 3), 'is_thick': is_thick})

    # day blocks
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    day_blocks = {d: [] for d in day_order}

    # helper to compute left/width pct from minutes
    def pct_from_minutes(start_min, end_min):
        s = max(start_min, MIN_START)
        e = min(end_min, MAX_END)
        if e <= s:
            return None, None
        left_pct = ((s - MIN_START) / total_minutes) * 100.0
        width_pct = ((e - s) / total_minutes) * 100.0
        return round(left_pct, 3), round(width_pct, 3)

    # add classes (use real start/end minutes; breaks will be added below)
    for e in entries:
        s_min = e.start_time.hour*60 + e.start_time.minute
        e_min = e.end_time.hour*60 + e.end_time.minute
        left_pct, width_pct = pct_from_minutes(s_min, e_min)
        if left_pct is None:
            continue
        day_blocks[e.day_of_week].append({
            'id': e.id,
            'title': e.course.name if getattr(e, 'course', None) else 'Class',
            'start_str': e.start_time.strftime('%I:%M %p'),
            'end_str': e.end_time.strftime('%I:%M %p'),
            'left_pct': left_pct,
            'width_pct': width_pct,
            'is_break': False
        })

    # ========= BREAKS (exact minutes, with letters per day) =========
    MORNING_BREAK_LETTERS = ['B', 'R', 'E', 'A', 'K']  # Monday → Friday
    AFTERNOON_BREAK_LETTERS = ['L', 'U', 'N', 'C', 'H']

    BREAKS = [
        {'title': 'Morning Break', 'start_min': 10*60, 'end_min': 10*60+25, 'letters': MORNING_BREAK_LETTERS},
        {'title': 'Lunch Break',   'start_min': 12*60+30, 'end_min': 12*60+55, 'letters': AFTERNOON_BREAK_LETTERS},
    ]

    for i, day in enumerate(day_order):
        for br in BREAKS:
            left_pct, width_pct = pct_from_minutes(br['start_min'], br['end_min'])
            if left_pct is None:
                continue
            day_blocks[day].append({
                'id': None,
                'title': br['letters'][i],  # Use letter instead of full name
                'start_str': f"{br['start_min']//60:02d}:{br['start_min']%60:02d}",
                'end_str': f"{br['end_min']//60:02d}:{br['end_min']%60:02d}",
                'left_pct': left_pct,
                'width_pct': width_pct,
                'is_break': True
            })

    # sort blocks per day
    for d in day_order:
        day_blocks[d].sort(key=lambda x: x['left_pct'])

    # also build CSS grid-template-columns value (percent list)
    col_template = ' '.join(f'{slot["width_pct"]}%' for slot in time_ticks)

    return render_template(
        'student/timetable.html',
        student_class=profile.current_class,
        time_ticks=time_ticks,
        day_blocks=day_blocks,
        vlines=vlines,
        col_template=col_template,
        total_minutes=total_minutes,
        download_ts=int(datetime.utcnow().timestamp())
    )

@student_bp.route('/download_timetable')
@login_required
def download_timetable():
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from datetime import datetime
    from flask import send_file, flash, redirect, url_for

    student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not student_profile:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('student.view_timetable'))

    student_class = student_profile.current_class

    timetable_entries = TimetableEntry.query \
        .filter_by(assigned_class=student_class) \
        .join(Course, TimetableEntry.course_id == Course.id) \
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time) \
        .all()

    if not timetable_entries:
        flash('No timetable available to download.', 'warning')
        return redirect(url_for('student.view_timetable'))

    # === TIME SLOTS ===
    TIME_SLOTS = [
        (8*60, 9*60),
        (9*60, 10*60),
        (10*60, 10*60+30),
        (10*60+30, 11*60+30),
        (11*60+30, 12*60+30),
        (12*60+30, 13*60),
        (13*60, 14*60),
        (14*60, 15*60),
        (15*60, 16*60),
        (16*60, 17*60),
    ]
    MIN_START = TIME_SLOTS[0][0]
    MAX_END = TIME_SLOTS[-1][1]
    total_minutes = MAX_END - MIN_START

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

    # Break letters
    MORNING_LETTERS = ['B', 'R', 'E', 'A', 'K']
    LUNCH_LETTERS = ['L', 'U', 'N', 'C', 'H']
    BREAKS = [
        {'start_min': 10*60, 'end_min': 10*60+25, 'letters': MORNING_LETTERS},
        {'start_min': 12*60+30, 'end_min': 12*60+55, 'letters': LUNCH_LETTERS},
    ]

    # Build header labels & column widths
    header = ['Day / Time']
    col_widths = [1.2 * inch]
    total_width = 10.5 * inch
    remaining_width = total_width - col_widths[0]

    for start, end in TIME_SLOTS:
        mins = end - start
        width = remaining_width * (mins / total_minutes)
        col_widths.append(width)
        label = f"{start//60:02d}:{start%60:02d} - {end//60:02d}:{end%60:02d}"
        header.append(label)

    # PDF Paragraph style for courses / breaks
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        'cell_style',
        parent=styles['Normal'],
        alignment=1,  # center
        fontSize=9,
        leading=10,
        wordWrap='CJK',  # wrap long names
    )

    # Build timetable matrix
    timetable_matrix = []
    now = datetime.now()
    today_name = now.strftime('%A')

    for i, day in enumerate(days):
        row = [day]  # first column is plain string (day)
        for start, end in TIME_SLOTS:
            match = next(
                (e for e in timetable_entries 
                 if e.day_of_week == day and 
                    (e.start_time.hour*60 + e.start_time.minute) == start),
                None
            )
            if match:
                row.append(Paragraph(match.course.name, cell_style))
            else:
                letter = None
                for br in BREAKS:
                    if start >= br['start_min'] and start < br['end_min']:
                        letter = br['letters'][i]
                        break
                row.append(Paragraph(letter if letter else "—", cell_style))
        timetable_matrix.append(row)

    data = [header] + timetable_matrix

    # PDF Generation
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=inch/2, rightMargin=inch/2,
                            topMargin=inch/2, bottomMargin=inch/2)
    elements = []

    elements.append(Paragraph(f"<b>Class Timetable: {student_class}</b>", styles['Title']))
    elements.append(Spacer(1, 12))

    table = Table(data, colWidths=col_widths, repeatRows=1)

    # Modern colorful table style
    table_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4A90E2")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
    ])

    # Row colors + today highlight + break letters
    for i, row in enumerate(timetable_matrix):
        bg_color = colors.HexColor("#f0f4f8") if i % 2 == 0 else colors.white
        table_style.add('BACKGROUND', (0,i+1), (-1,i+1), bg_color)
        if row[0] == today_name:
            table_style.add('BACKGROUND', (0,i+1), (-1,i+1), colors.HexColor("#FFF4CC"))

        for j, val in enumerate(row[1:], start=1):
            text = val.getPlainText().strip()
            if text in MORNING_LETTERS + LUNCH_LETTERS:
                table_style.add('BACKGROUND', (j,i+1), (j,i+1), colors.HexColor("#FFD966"))
                table_style.add('TEXTCOLOR', (j,i+1), (j,i+1), colors.HexColor("#222222"))
                table_style.add('FONTNAME', (j,i+1), (j,i+1), 'Helvetica-Bold')

    table.setStyle(table_style)
    elements.append(table)

    elements.append(Spacer(1,12))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%d %b %Y %I:%M %p')}", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"{student_class}_timetable.pdf",
                     mimetype='application/pdf')

# Appointment Booking System
from collections import defaultdict

@student_bp.route('/book-appointment', methods=['GET', 'POST'])
@login_required
def book_appointment():
    # Only fetch unbooked slots
    available_slots = AppointmentSlot.query.filter_by(is_booked=False).all()

    # Pass slots directly to template
    slots = []
    for slot in available_slots:
        teacher_user = slot.teacher.user  # Get the related User
        slots.append({
            'id': slot.id,
            'date': slot.date,
            'start_time': slot.start_time,
            'end_time': slot.end_time,
            'teacher_name': f"{teacher_user.first_name} {teacher_user.last_name}"
        })

    if request.method == 'POST':
        slot_id = request.form['slot_id']
        note = request.form.get('note', '')
        slot = AppointmentSlot.query.get_or_404(slot_id)

        if slot.is_booked:
            flash('Slot already booked.', 'danger')
            return redirect(url_for('student.book_appointment'))

        student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
        if not student_profile:
            flash('Student profile not found.', 'danger')
            return redirect(url_for('student.book_appointment'))

        booking = AppointmentBooking(
            student_id=student_profile.id,
            slot_id=slot.id,
            note=note
        )
        slot.is_booked = True
        db.session.add(booking)
        db.session.add(booking)
        db.session.commit()

        flash('Appointment booked successfully.', 'success')
        return redirect(url_for('student.my_appointments'))

    return render_template('student/book_appointment.html', slots=slots)

from sqlalchemy.orm import joinedload

@student_bp.route('/my-appointments')
@login_required
def my_appointments():
    student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not student_profile:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('student.book_appointment'))

    bookings = AppointmentBooking.query \
        .filter_by(student_id=student_profile.id) \
        .options(joinedload(AppointmentBooking.slot).joinedload(AppointmentSlot.teacher)) \
        .all()

    return render_template('student/my_appointments.html', bookings=bookings)

# Fees Management
@student_bp.route('/fees')
@login_required
def student_fees():
    # Restrict to students
    if current_user.role != 'student':
        abort(403)

    fees = StudentFeeBalance.query.filter_by(
        student_id=current_user.id
    ).order_by(StudentFeeBalance.id.desc()).all()

    transactions = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id
    ).order_by(StudentFeeTransaction.timestamp.desc()).all()

    return render_template(
        'student/fees.html',
        fees=fees,
        transactions=transactions
    )

@student_bp.route('/pay-fees')
@login_required
def pay_fees():
    if current_user.role != 'student':
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.index'))

    # Get selected year and semester from query parameters
    year = request.args.get('year')
    semester = request.args.get('semester')

    # Render empty view if filters are missing
    if not year or not semester:
        flash("Please select an academic year and semester.", "warning")
        return render_template(
            'student/pay_fees.html',
            assigned_fees=[],
            total_fee=0,
            current_balance=0,
            pending_balance=0,
            transactions=[],
            year=year,
            semester=semester
        )

    student_class = current_user.student_profile.current_class

    # Fetch assigned fees for class/year/semester
    assigned_fees = ClassFeeStructure.query.filter_by(
        class_level=student_class,
        academic_year=year,
        semester=semester
    ).all()
    total_fee = sum(fee.amount for fee in assigned_fees)

    # Approved payments
    approved_txns = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester,
        is_approved=True
    ).all()
    current_balance = sum(txn.amount for txn in approved_txns)

    # Pending payments
    pending_txns = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester,
        is_approved=False
    ).all()
    pending_balance = sum(txn.amount for txn in pending_txns)

    # All transactions
    transactions = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester
    ).order_by(StudentFeeTransaction.timestamp.desc()).all()

    return render_template(
        'student/pay_fees.html',
        assigned_fees=assigned_fees,
        total_fee=total_fee,
        current_balance=current_balance,
        pending_balance=pending_balance,
        transactions=transactions,
        year=year,
        semester=semester
    )

@student_bp.route('/download-receipt/<int:txn_id>')
@login_required
def download_receipt(txn_id):
    txn = StudentFeeTransaction.query.get_or_404(txn_id)
    if txn.student_id != current_user.id or not txn.is_approved:
        abort(403)

    filename = f"receipt_{txn.id}.pdf"
    filepath = os.path.join(current_app.config['RECEIPT_FOLDER'], filename)

    if not os.path.exists(filepath):
        flash("Receipt not found. Please contact admin.", "danger")
        return redirect(url_for('student.pay_fees', year=txn.academic_year, semester=txn.semester))

    return send_file(filepath, as_attachment=True)


@student_bp.route('/profile')
@login_required
def profile():
    if not current_user.is_student:
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    return render_template('student/profile.html', profile=profile, user=current_user)

@student_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if not current_user.is_student:
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    if request.method == 'POST':
        profile.phone = request.form.get('phone')
        profile.email = request.form.get('email')
        profile.address = request.form.get('address')
        profile.city = request.form.get('city')
        profile.postal_code = request.form.get('postal_code')

        profile.blood_group = request.form.get('blood_group')
        profile.medical_conditions = request.form.get('medical_conditions')

        profile.emergency_contact_name = request.form.get('emergency_contact_name')
        profile.emergency_contact_number = request.form.get('emergency_contact_number')

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('student.profile'))

    return render_template('student/edit_profile.html', profile=profile)

@student_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if current_user.check_password(form.current_password.data):
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password updated successfully!', 'success')
            return redirect(url_for('student.profile'))
        else:
            flash('Current password is incorrect.', 'danger')
    return render_template('student/change_password.html', form=form)

from collections import defaultdict

@student_bp.route('/notifications')
@login_required
def student_notifications():
    """
    Show grouped notifications by title/category.
    """
    recipients = (
        NotificationRecipient.query
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(NotificationRecipient.user_id == current_user.user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )

    grouped = defaultdict(list)
    for r in recipients:
        grouped[r.notification.title].append(r)

    # sort groups by most recent notification
    grouped_notifications = sorted(
        grouped.items(),
        key=lambda g: g[1][0].notification.created_at,
        reverse=True
    )

    return render_template(
        'student/notifications.html',
        grouped_notifications=grouped_notifications
    )

@student_bp.route('/notifications/group/<string:title>')
@login_required
def view_notification_group(title):
    """
    Show all notifications under a single title group.
    """
    recipients = (
        NotificationRecipient.query
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(NotificationRecipient.user_id == current_user.user_id,
                Notification.title == title)
        .order_by(Notification.created_at.desc())
        .all()
    )

    # mark all as read
    for r in recipients:
        if not r.is_read:
            r.is_read = True
            r.read_at = datetime.utcnow()
    db.session.commit()

    return render_template('student/notification_detail.html', title=title, recipients=recipients)


@student_bp.route('/notifications/mark_read/<int:recipient_id>', methods=['POST'])
@login_required
def mark_notification_read(recipient_id):
    recipient = NotificationRecipient.query.filter_by(
        id=recipient_id, user_id=current_user.user_id
    ).first_or_404()

    if not recipient.is_read:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({"success": True, "id": recipient_id})

@student_bp.route('/notifications/delete/<int:recipient_id>', methods=['POST'])
@login_required
def delete_notification(recipient_id):
    """
    Delete a single notification for the logged-in student.
    """
    recipient = NotificationRecipient.query.filter_by(
        id=recipient_id, user_id=current_user.user_id
    ).first_or_404()

    db.session.delete(recipient)
    db.session.commit()

    return jsonify({"success": True, "id": recipient_id})

@student_bp.route('/notifications/delete_group/<string:title>', methods=['POST'])
@login_required
def delete_notification_group(title):
    """
    Delete all notifications under a given title for the current user.
    """
    recipients = (
        NotificationRecipient.query
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(
            NotificationRecipient.user_id == current_user.user_id,
            Notification.title == title
        )
        .all()
    )

    if not recipients:
        return jsonify({'success': False, 'message': 'No notifications found'}), 404

    # Delete each recipient entry
    for r in recipients:
        db.session.delete(r)
    db.session.commit()

    return jsonify({'success': True})


def format_time(t):
    # expects time object
    return t.strftime('%I:%M%p').lstrip('0').replace('AM','AM').replace('PM','PM')

@student_bp.route('/exam-timetable', methods=['GET', 'POST'])
@login_required
def exam_timetable_page():
    return render_template('student/exam_timetable_input.html')

def generate_logo_qr(data: str,
                     logo_path: str,
                     final_size: int = 300,
                     logo_fraction: float = 0.45,
                     box_size: int = 24,
                     border: int = 10) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    qr_px = qr_img.size[0]
    logo_px = int(qr_px * logo_fraction)
    if logo_px <= 0:
        raise ValueError("logo_fraction too small or qr image size wrong")
    logo = Image.open(logo_path).convert("RGBA")
    logo.thumbnail((logo_px, logo_px), Image.Resampling.LANCZOS)
    lw, lh = logo.size
    pad = max(6, int(logo_px * 0.06))
    bg_size = (lw + pad*2, lh + pad*2)
    circle_bg = Image.new("RGBA", bg_size, (255,255,255,0))
    mask = Image.new("L", bg_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0,0,bg_size[0]-1,bg_size[1]-1), fill=255)
    white_bg = Image.new("RGBA", bg_size, (255,255,255,255))
    circle_bg.paste(white_bg, (0,0), mask)
    pos = ((qr_px - bg_size[0]) // 2, (qr_px - bg_size[1]) // 2)
    qr_img.paste(circle_bg, pos, circle_bg)
    logo_pos = (pos[0] + pad, pos[1] + pad)
    qr_img.paste(logo, logo_pos, logo)
    if final_size != qr_px:
        qr_img = qr_img.resize((final_size, final_size), Image.Resampling.LANCZOS)
    return qr_img


@student_bp.route('/exam-timetable/download', methods=['POST'])
@login_required
def download_student_exam_timetable():
    index_number = request.form.get("index_number")
    if not index_number:
        flash("Please enter a valid index number.", "danger")
        return redirect(url_for('student.exam_timetable_page'))

    profile = StudentProfile.query.join(User).filter(User.user_id == index_number).first()
    if not profile:
        flash("Index number not found.", "danger")
        return redirect(url_for('student.exam_timetable_page'))

    entries = ExamTimetableEntry.query.filter(
        ((ExamTimetableEntry.student_index == index_number) |
         (ExamTimetableEntry.assigned_class == profile.current_class))
    ).order_by(
        ExamTimetableEntry.date,
        ExamTimetableEntry.start_time
    ).all()

    if not entries:
        flash("No exam timetable found for this index number.", "warning")
        return redirect(url_for('student.exam_timetable_page'))

    # Layout constants (tweak these for different looks)
    margin = 40
    block_spacing = 18
    block_corner_radius = 6
    page_width, page_height = letter
    content_width = page_width - 2 * margin

    # QR drawing sizes (display vs generation)
    qr_display_size = 110            # size drawn on PDF (px)
    qr_generate_size = qr_display_size * 2  # generate higher-res QR and scale down
    qr_right_margin = 18

    # Text layout inside block
    left_col_x = margin + 16
    label_col_x = left_col_x
    value_col_x = left_col_x + 60
    line_height = 14
    course_wrap_width = 36  # approx characters before wrapping; tweak if needed

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # -------- Header --------
    p.setFillColor(colors.HexColor("#1f77b4"))
    p.rect(0, height-70, width, 70, fill=True, stroke=False)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width/2, height-45, "END OF SEMESTER EXAMINATION TIMETABLE")
    p.setFont("Helvetica", 10)
    p.drawCentredString(width/2, height-60, "Academic Year")

    # starting top y for first block
    y_top = height - 90

    for e in entries:
        # Split fields into left and right columns
        left_fields = [
        ("Name:", f"{profile.user.first_name} {profile.user.last_name}"),
        ("Index:", index_number),
        ("Course:", e.course or "")
    ]
    right_fields = [
        ("Time:", f"{format_time(e.start_time)} - {format_time(e.end_time)}"),
        ("Date:", e.date.strftime('%A, %d %B %Y')),
        ("Room:", e.room or ""),
        ("Building:", e.building or ""),
        ("Floor:", e.floor or "")
    ]

    # Wrap long course name for left column
    wrapped_course = textwrap.wrap(left_fields[2][1], width=24)
    left_fields[2] = ("Course:", "\n".join(wrapped_course))

    # Layout constants for this block
    line_height = 14
    top_padding = 20           # distance from top of block to first line (was small before)
    bottom_padding = 16
    col_gap = 20               # gap between left and right column start X
    left_x = margin + 16
    right_x = margin + content_width / 2
    value_offset = 60          # label -> value offset

    # compute number of text lines required (largest of the two columns)
    left_lines = sum(v.count("\n") + 1 for _, v in left_fields)
    right_lines = sum(v.count("\n") + 1 for _, v in right_fields)
    text_lines = max(left_lines, right_lines)

    # block height: enough for text lines and QR area
    text_block_height = text_lines * line_height + top_padding + bottom_padding
    block_height = max(text_block_height, qr_display_size + top_padding + bottom_padding)
    block_bottom = y_top - block_height

    # new page check
    if block_bottom < 40:
        p.showPage()
        # redraw header
        p.setFillColor(colors.HexColor("#1f77b4"))
        p.rect(0, height-70, width, 70, fill=True, stroke=False)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 16)
        p.drawCentredString(width/2, height-45, "END OF SEMESTER EXAMINATION TIMETABLE")
        p.setFont("Helvetica", 10)
        p.drawCentredString(width/2, height-60, "Academic Year")
        y_top = height - 90
        block_bottom = y_top - block_height

    # draw background block & accent
    p.setFillColor(colors.HexColor("#f8f9fa"))
    p.roundRect(margin, block_bottom, content_width, block_height, block_corner_radius, fill=True, stroke=False)
    p.setFillColor(colors.HexColor("#1f77b4"))
    p.roundRect(margin+8, block_bottom+8, 6, block_height-16, 3, fill=True, stroke=False)

    # start text at top_padding below block top (safer vertical position)
    cur_y = block_bottom + block_height - top_padding

    # Draw left column
    p.setFont("Helvetica-Bold", 10)
    for label, value in left_fields:
        p.drawString(left_x, cur_y, label)
        p.setFont("Helvetica", 10)
        for subline in value.split("\n"):
            p.drawString(left_x + value_offset, cur_y, subline)
            cur_y -= line_height
        p.setFont("Helvetica-Bold", 10)

    # Draw right column (start from same top baseline)
    cur_y_right = block_bottom + block_height - top_padding
    p.setFont("Helvetica-Bold", 10)
    for label, value in right_fields:
        p.drawString(right_x, cur_y_right, label)
        p.setFont("Helvetica", 10)
        for subline in value.split("\n"):
            p.drawString(right_x + value_offset, cur_y_right, subline)
            cur_y_right -= line_height
        p.setFont("Helvetica-Bold", 10)

    # Prepare & place QR (bottom-right)
    qr_data = (
        f"Student: {profile.user.first_name} {profile.user.last_name}\n"
        f"Index: {profile.user.user_id}\n"
        f"Course: {e.course}\n"
        f"Date: {e.date.strftime('%A, %d %B %Y')}\n"
        f"Time: {format_time(e.start_time)} - {format_time(e.end_time)}\n"
        f"Building: {e.building}\nRoom: {e.room}"
    )
    qr_img = generate_logo_qr(qr_data, logo_path='static/logo.png',
                              final_size=qr_generate_size, logo_fraction=0.45,
                              box_size=24, border=10)
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    qr_reader = ImageReader(qr_buffer)
    qr_x = margin + content_width - qr_right_margin - qr_display_size
    qr_y = block_bottom + bottom_padding
    p.drawImage(qr_reader, qr_x, qr_y, qr_display_size, qr_display_size, preserveAspectRatio=True, mask='auto')

    # divider + update y_top
    p.setStrokeColor(colors.HexColor("#e6e6e6"))
    p.setLineWidth(0.5)
    p.line(margin+8, block_bottom - 6, margin+content_width-8, block_bottom - 6)

    y_top = block_bottom - block_spacing

    # finish up
    p.showPage()
    p.save()
    buffer.seek(0)

    filename = f"exam_timetable_{index_number}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

# Teacher Assessment System
@student_bp.route('/teacher-assessment', methods=['GET', 'POST'])
@login_required
def teacher_assessment():
    if not current_user.is_student:
        abort(403)

    # Active assessment period
    period = TeacherAssessmentPeriod.query.filter_by(is_active=True).first()
    if not period:
        flash("Teacher assessment is currently closed.", "warning")
        return redirect(url_for('student.dashboard'))

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not profile:
        abort(404)

    # -----------------------------
    # STEP 1 DATA (teachers list)
    # -----------------------------
    teachers = (
        db.session.query(
            User,
            db.func.group_concat(Course.name, ', ').label('courses')
        )
        .join(TeacherProfile, TeacherProfile.user_id == User.user_id)
        .join(TeacherCourseAssignment, TeacherCourseAssignment.teacher_id == TeacherProfile.id)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .filter(
            User.role == 'teacher',
            Course.assigned_class == profile.current_class
        )
        .group_by(User.id)
        .all()
    )

    # Already assessed teachers
    assessed_teacher_ids = {
        a.teacher_id
        for a in TeacherAssessment.query.filter_by(
            student_id=current_user.user_id,
            period_id=period.id
        ).all()
    }

    # Calculate progress
    total_teachers = len(teachers)
    completed_count = sum(1 for teacher, _ in teachers if teacher.user_id in assessed_teacher_ids)
    progress_percent = int((completed_count / total_teachers) * 100) if total_teachers else 0

    # -----------------------------
    # STEP 2 DATA (questions)
    # -----------------------------
    questions_behavior = TeacherAssessmentQuestion.query.filter_by(
        category='teacher_behavior', is_active=True
    ).all()

    questions_response = TeacherAssessmentQuestion.query.filter_by(
        category='student_response', is_active=True
    ).all()

    # -----------------------------
    # STEP 2: Selected teacher
    # -----------------------------
    selected_teacher = None
    teacher_user_id = request.args.get('teacher')

    if teacher_user_id:
        if teacher_user_id in assessed_teacher_ids:
            flash("You have already assessed this teacher.", "info")
            return redirect(url_for('student.teacher_assessment'))

        selected_teacher = User.query.filter_by(
            user_id=teacher_user_id,
            role='teacher'
        ).first_or_404()

    # -----------------------------
    # SUBMIT ASSESSMENT
    # -----------------------------
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')

        exists = TeacherAssessment.query.filter_by(
            student_id=current_user.user_id,
            teacher_id=teacher_id,
            period_id=period.id
        ).first()

        if exists:
            flash("You have already assessed this teacher.", "danger")
            return redirect(url_for('student.teacher_assessment'))

        assessment = TeacherAssessment(
            student_id=current_user.user_id,
            teacher_id=teacher_id,
            class_name=profile.current_class,
            period_id=period.id
        )
        db.session.add(assessment)
        db.session.flush()

        for q in questions_behavior + questions_response:
            score = request.form.get(f'q_{q.id}')
            if score:
                db.session.add(
                    TeacherAssessmentAnswer(
                        assessment_id=assessment.id,
                        question_id=q.id,
                        score=int(score)
                    )
                )

        db.session.commit()
        flash("Assessment submitted successfully.", "success")
        return redirect(url_for('student.teacher_assessment'))

    return render_template(
        'student/teacher_assessment.html',
        teachers=teachers,
        assessed_teacher_ids=assessed_teacher_ids,
        selected_teacher=selected_teacher,
        questions_behavior=questions_behavior,
        questions_response=questions_response,
        total_teachers=total_teachers,
        completed_count=completed_count,
        progress_percent=progress_percent
    )





