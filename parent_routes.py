from flask import Blueprint, render_template, abort, flash, redirect, url_for, request, send_file, current_app, jsonify
from flask_login import login_required, current_user, login_user
from forms import ChangePasswordForm, ParentLoginForm
from models import User, ParentProfile, ParentChildLink, StudentProfile, Assignment, StudentQuizSubmission, Quiz, AttendanceRecord, StudentFeeBalance, StudentFeeTransaction , ClassFeeStructure , Notification, NotificationRecipient, TimetableEntry
from datetime import datetime
import os, logging
from utils.extensions import db
from werkzeug.utils import secure_filename

parent_bp = Blueprint("parent", __name__, url_prefix="/parent")

logger = logging.getLogger('parent_login')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()  # logs to console
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@parent_bp.route('/login', methods=['GET', 'POST'])
def parent_login():
    form = ParentLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        logger.debug(f"Parent login attempt: user_id='{user_id}', username='{username}'")

        try:
            user = None
            # First try lookup by user_id
            if user_id:
                user = User.query.filter_by(user_id=user_id, role='parent').first()
                logger.debug(f"Lookup by user_id returned: {user}")

            # If not found, try username (case-insensitive)
            if not user and username:
                user = User.query.filter(User.username.ilike(username), User.role == 'parent').first()
                logger.debug(f"Lookup by username returned: {user}")

            if not user:
                logger.warning(f"No parent user found for user_id='{user_id}', username='{username}'")
                flash("Invalid parent credentials.", "danger")
                return render_template('parent/login.html', form=form)

            # Check password
            if not user.check_password(password):
                logger.warning(f"Password check failed for user_id='{user.user_id}', username='{user.username}'")
                flash("Invalid parent credentials.", "danger")
                return render_template('parent/login.html', form=form)

            # Successful login
            login_user(user)
            logger.info(f"Parent '{user.first_name} {user.last_name}' logged in successfully (user_id={user.user_id})")
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for('parent.dashboard'))

        except Exception as e:
            logger.error(f"Exception during parent login: {e}", exc_info=True)
            flash(f"An error occurred during login. Check logs for details.", "danger")

    return render_template('parent/login.html', form=form)
    
# ------------------------
# Parent Dashboard
# ------------------------
@parent_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first()

    children = []
    if parent_profile:
        children_links = ParentChildLink.query.filter_by(parent_id=parent_profile.id).all()
        for link in children_links:
            student = StudentProfile.query.filter_by(id=link.student_id).first()
            user = User.query.filter_by(user_id=student.user_id).first() if student else None
            if student and user:
                children.append((student, user))

    total_children = len(children)

    # Optional: compute unread notifications for parent (if you have a Notification model)
    try:
        unread_notifications_count = db.session.query(Notification).filter_by(user_id=current_user.user_id, read=False).count()
    except Exception:
        unread_notifications_count = 0

    # Optional: compute upcoming items across children (exams/assignments/events)
    try:
        # Example placeholder. Replace with real queries for events/assignments linked to student's class
        upcoming_count = 0
        for sp, user in children:
            # if you have a helper, you might fetch the next event/assignment per student
            next_item = None
            # e.g. next_item = get_next_event_for_student(sp.id)
            if next_item:
                upcoming_count += 1
            # attach next_item to student_profile so template can show it
            sp.next_event = next_item
    except Exception:
        upcoming_count = 0

    # attach some lightweight counts to each student_profile for the UI if needed
    for sp, user in children:
        try:
            sp.notifications_count = 0  # replace with actual count query if you have it
        except Exception:
            sp.notifications_count = 0

    return render_template(
        'parent/dashboard.html',
        children=children,
        total_children=total_children,
        unread_notifications_count=unread_notifications_count,
        upcoming_count=upcoming_count,
        utcnow=datetime.utcnow  # small helper for Jinja age calc
    )

@parent_bp.route('/profile')
@login_required
def profile():
    if current_user.role != 'parent':
        abort(403)

    profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first()
    return render_template('parent/profile.html', profile=profile)

@parent_bp.route('/change_password', methods=['GET', 'POST'])
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
    return render_template('parent/change_password.html', form=form)

# ------------------------
# View All Children
# ------------------------
@parent_bp.route('/children')
@login_required
def view_children():
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    # Get linked children directly from relationship
    children = (
        db.session.query(User)
        .join(StudentProfile, StudentProfile.user_id == User.user_id)
        .join(ParentChildLink, ParentChildLink.student_id == StudentProfile.id)
        .filter(ParentChildLink.parent_id == parent_profile.id)
        .all()
    )

    if not children:
        flash("No children linked to your account.", "info")

    return render_template('parent/view_children.html', children=children)


@parent_bp.route('/children/<int:child_id>')
@login_required
def view_child_detail(child_id):
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    # Query child
    child = (
        db.session.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.user_id)
        .join(ParentChildLink, ParentChildLink.student_id == StudentProfile.id)
        .filter(
            ParentChildLink.parent_id == parent_profile.id,
            StudentProfile.id == child_id
        )
        .first()
    )

    if not child:
        flash("No such child linked to your account.", "warning")
        return redirect(url_for('parent.children'))

    student_profile, user = child

    return render_template(
        'parent/child_detail.html',
        profile=student_profile,
        user=user
    )

@parent_bp.route('/child/<int:child_id>/attendance')
@login_required
def view_attendance(child_id):
    if current_user.role != 'parent':
        abort(403)

    # Verify that this child belongs to the current parent
    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()
    link = ParentChildLink.query.filter_by(parent_id=parent_profile.id, student_id=child_id).first()
    if not link:
        abort(403)

    student_profile = StudentProfile.query.filter_by(id=child_id).first_or_404()
    user = User.query.filter_by(user_id=student_profile.user_id).first_or_404()

    # Fetch attendance records for this student (order by date)
    attendance_records = (db.session.query(AttendanceRecord)
                          .filter_by(student_id=student_profile.id)
                          .order_by(AttendanceRecord.date.desc())
                          .all())

    # Format records for display
    formatted_records = [{
        'date': r.date.strftime('%d %b %Y'),
        'is_present': r.is_present
    } for r in attendance_records]

    return render_template(
        'parent/view_attendance.html',
        student=student_profile,
        user=user,
        records=formatted_records
    )

@parent_bp.route('/report/<int:child_id>')
@login_required
def view_student_report(child_id):
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    # Ensure this child belongs to the parent
    student_profile, user = (
        db.session.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.user_id)
        .join(ParentChildLink, ParentChildLink.student_id == StudentProfile.id)
        .filter(
            ParentChildLink.parent_id == parent_profile.id,
            StudentProfile.id == child_id
        )
        .first_or_404()
    )

    # ---------------------------
    # QUIZZES (20% of final grade)
    # ---------------------------
    quiz_results = (
        StudentQuizSubmission.query
        .join(Quiz, StudentQuizSubmission.quiz_id == Quiz.id)
        .filter(StudentQuizSubmission.student_id == user.id)
        .all()
    )

    total_quiz_score = 0
    total_quiz_max = 0

    for q in quiz_results:
        quiz_max = q.quiz.max_score  # property that sums question points
        total_quiz_score += q.score
        total_quiz_max += quiz_max

    quiz_percentage = (total_quiz_score / total_quiz_max * 100) if total_quiz_max > 0 else 0
    quiz_weighted = quiz_percentage * 0.20  # 20% weight

    # ---------------------------
    # EXAMS (70% of final grade)
    # ---------------------------
    # You’ll need a model for Exam and StudentExamSubmission
    exam_results = []  # fetch from your DB
    total_exam_score = sum(e.score for e in exam_results)
    total_exam_max = sum(e.total_score for e in exam_results)

    exam_percentage = (total_exam_score / total_exam_max * 100) if total_exam_max > 0 else 0
    exam_weighted = exam_percentage * 0.70  # 70% weight

    # ---------------------------
    # ASSIGNMENTS (10% of final grade)
    # ---------------------------
    assignment_results = []  # fetch from DB
    total_assign_score = sum(a.score for a in assignment_results)
    total_assign_max = sum(a.total_score for a in assignment_results)

    assign_percentage = (total_assign_score / total_assign_max * 100) if total_assign_max > 0 else 0
    assign_weighted = assign_percentage * 0.10  # 10% weight

    # ---------------------------
    # FINAL GRADE
    # ---------------------------
    final_percentage = quiz_weighted + exam_weighted + assign_weighted

    assignments = Assignment.query.filter_by(assigned_class=student_profile.current_class).all()
    attendance_records = AttendanceRecord.query.filter_by(student_id=user.id).all()

    return render_template(
        'parent/student_report.html',
        student=student_profile,
        quiz_results=quiz_results,
        assignments=assignments,
        attendance_records=attendance_records,
        quiz_percentage=quiz_percentage,
        exam_percentage=exam_percentage,
        assign_percentage=assign_percentage,
        quiz_weighted=quiz_weighted,
        exam_weighted=exam_weighted,
        assign_weighted=assign_weighted,
        final_percentage=final_percentage
    )

@parent_bp.route('/reports')
@login_required
def reports_list():
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    children = (
        db.session.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.user_id)
        .join(ParentChildLink, ParentChildLink.student_id == StudentProfile.id)
        .filter(ParentChildLink.parent_id == parent_profile.id)
        .all()
    )

    return render_template('parent/reports_list.html', children=children)


@parent_bp.app_context_processor
def inject_parent_notification_count():
    unread_count = 0
    if current_user.is_authenticated and hasattr(current_user, "user_id"):
        unread_count = NotificationRecipient.query.filter_by(
            user_id=current_user.user_id,
            is_read=False
        ).count()
    return dict(unread_count=unread_count)

@parent_bp.route('/notifications')
@login_required
def notifications():
    notifications = (
        NotificationRecipient.query
        .join(Notification)  # use the class, not a string
        .filter(NotificationRecipient.user_id == current_user.user_id)
        .order_by(Notification.created_at.desc())  # order by the Notification's created_at
        .all()
    )
    return render_template('parent/notifications.html', notifications=notifications)

@parent_bp.route('/notifications/view/<int:recipient_id>')
@login_required
def view_parent_notification(recipient_id):
    recipient = (
        NotificationRecipient.query
        .join(Notification)
        .filter(NotificationRecipient.id == recipient_id,
                NotificationRecipient.user_id == current_user.user_id)
        .first_or_404()
    )

    if not recipient.is_read:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        db.session.commit()

    return render_template('parent/notification_detail.html', recipient=recipient)

@parent_bp.route('/notifications/mark_read/<int:recipient_id>', methods=['POST'])
@login_required
def mark_parent_notification_read(recipient_id):
    recipient = NotificationRecipient.query.filter_by(
        id=recipient_id, user_id=current_user.user_id
    ).first_or_404()

    if not recipient.is_read:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({"success": True, "id": recipient_id})

@parent_bp.route('/notifications/unread_count')
@login_required
def get_unread_count():
    unread_count = NotificationRecipient.query.filter_by(
        user_id=current_user.user_id,
        is_read=False
    ).count()
    return jsonify({"unread_count": unread_count})

@parent_bp.route('/fees')
@login_required
def student_fees():
    # Restrict to students
    if current_user.role != 'parent':
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

@parent_bp.route('/pay-fees/<int:student_id>', methods=['GET', 'POST'])
@login_required
def parent_pay_fees(student_id):
    if current_user.role != 'parent':
        abort(403)

    student = User.query.get_or_404(student_id)
    if not student.student_profile:
        flash("This student does not have a profile yet.", "warning")
        return redirect(url_for('parent.view_children'))

    student_class = student.student_profile.current_class

    # Get all academic years for this class
    available_years = db.session.query(ClassFeeStructure.academic_year)\
                        .filter_by(class_level=student_class).distinct().all()
    available_years = [y[0] for y in available_years]

    # Get year/semester from query params
    year = request.args.get('year')
    semester = request.args.get('semester')

    assigned_fees = []
    total_fee = 0
    current_balance = 0
    pending_balance = 0
    transactions = []

    # Only load fees if both are selected
    if year and semester:
        assigned_fees = ClassFeeStructure.query.filter_by(
            class_level=student_class,
            academic_year=year,
            semester=semester
        ).all()
        total_fee = sum(fee.amount for fee in assigned_fees)

        approved_txns = StudentFeeTransaction.query.filter_by(
            student_id=student_id,
            academic_year=year,
            semester=semester,
            is_approved=True
        ).all()

        pending_txns = StudentFeeTransaction.query.filter_by(
            student_id=student_id,
            academic_year=year,
            semester=semester,
            is_approved=False
        ).all()

        current_balance = sum(txn.amount for txn in approved_txns)
        pending_balance = sum(txn.amount for txn in pending_txns)
        transactions = approved_txns + pending_txns

    if request.method == 'POST':
        # Server-side validation: user must select year and semester
        year_post = request.form.get('year')
        semester_post = request.form.get('semester')
        if not year_post or not semester_post:
            flash("Please select both academic year and semester before submitting.", "danger")
            return redirect(url_for('parent.parent_pay_fees', student_id=student_id))

        try:
            amount = float(request.form.get('amount'))
            if amount <= 0:
                raise ValueError("Amount must be greater than zero.")
        except Exception:
            flash("Invalid amount entered.", "danger")
            return redirect(url_for('parent.parent_pay_fees', student_id=student_id, year=year_post, semester=semester_post))

        description = request.form.get('description')
        proof = request.files.get('proof')
        filename = None
        if proof and proof.filename:
            filename = secure_filename(proof.filename)
            proof_path = os.path.join(current_app.config['PAYMENT_PROOF_FOLDER'], filename)
            proof.save(proof_path)

        new_txn = StudentFeeTransaction(
            student_id=student_id,
            academic_year=year_post,
            semester=semester_post,
            amount=amount,
            description=description,
            proof_filename=filename,
            is_approved=False
        )
        db.session.add(new_txn)
        db.session.commit()

        flash("Payment submitted successfully. Awaiting admin approval.", "info")
        return redirect(url_for('parent.parent_pay_fees', student_id=student_id, year=year_post, semester=semester_post))

    return render_template(
        'parent/pay_fees.html',
        student=student,
        assigned_fees=assigned_fees,
        total_fee=total_fee,
        current_balance=current_balance,
        pending_balance=pending_balance,
        transactions=transactions,
        year=year,
        semester=semester,
        available_years=available_years
    )

@parent_bp.route('/download-receipt/<int:txn_id>')
@login_required
def download_receipt(txn_id):
    txn = StudentFeeTransaction.query.get_or_404(txn_id)

    # Allow only owner student OR their parent
    if not (current_user.id == txn.student_id or current_user.role == 'parent'):
        abort(403)

    if not txn.is_approved:
        abort(403)

    filename = f"receipt_{txn.id}.pdf"
    filepath = os.path.join(current_app.config['RECEIPT_FOLDER'], filename)

    if not os.path.exists(filepath):
        flash("Receipt not found. Please contact admin.", "danger")
        return redirect(url_for('student.student_fees'))

    return send_file(filepath, as_attachment=True)

@parent_bp.route('/child/<int:student_id>/timetable')
@login_required
def view_child_timetable(student_id):
    if current_user.role != 'parent':
        abort(403)

    # Get parent profile
    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    # Verify the parent actually has this child
    link = ParentChildLink.query.filter_by(parent_id=parent_profile.id, student_id=student_id).first()
    if not link:
        abort(403)

    student = StudentProfile.query.get_or_404(student_id)

    # TIMETABLE LOGIC (reuse student timetable logic)
    entries = (
        TimetableEntry.query
        .filter_by(assigned_class=student.current_class)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time)
        .all()
    )

    # TIME SLOTS, day_blocks, vlines etc. (copy the same code you already have)
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

    time_ticks = []
    for start, end in TIME_SLOTS:
        width_pct = ((end - start) / total_minutes) * 100.0
        label = f"{(start//60)%12 or 12}:{start%60:02d} - {(end//60)%12 or 12}:{end%60:02d}"
        time_ticks.append({'start': start, 'end': end, 'label': label, 'width_pct': round(width_pct, 4)})

    cum = MIN_START
    vlines = []
    for start, end in TIME_SLOTS:
        cum += (end - start)
        cum_pct = ((cum - MIN_START) / total_minutes) * 100.0
        is_thick = ((end % 60) == 0)
        vlines.append({'left_pct': round(cum_pct, 3), 'is_thick': is_thick})

    day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday']
    day_blocks = {d: [] for d in day_order}

    def pct_from_minutes(start_min, end_min):
        s = max(start_min, MIN_START)
        e = min(end_min, MAX_END)
        if e <= s:
            return None, None
        left_pct = ((s - MIN_START) / total_minutes) * 100.0
        width_pct = ((e - s) / total_minutes) * 100.0
        return round(left_pct,3), round(width_pct,3)

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

    # Add breaks (same as student)
    MORNING_BREAK_LETTERS = ['B','R','E','A','K']
    AFTERNOON_BREAK_LETTERS = ['L','U','N','C','H']
    BREAKS = [
        {'title': 'Morning Break', 'start_min': 10*60, 'end_min': 10*60+25, 'letters': MORNING_BREAK_LETTERS},
        {'title': 'Lunch Break',   'start_min': 12*60+30, 'end_min': 12*60+55, 'letters': AFTERNOON_BREAK_LETTERS},
    ]
    for i, day in enumerate(day_order):
        for br in BREAKS:
            left_pct, width_pct = pct_from_minutes(br['start_min'], br['end_min'])
            if left_pct is None: continue
            day_blocks[day].append({
                'id': None,
                'title': br['letters'][i],
                'start_str': f"{br['start_min']//60:02d}:{br['start_min']%60:02d}",
                'end_str': f"{br['end_min']//60:02d}:{br['end_min']%60:02d}",
                'left_pct': left_pct,
                'width_pct': width_pct,
                'is_break': True
            })

    for d in day_order:
        day_blocks[d].sort(key=lambda x: x['left_pct'])

    col_template = ' '.join(f'{slot["width_pct"]}%' for slot in time_ticks)

    return render_template(
        'parent/child_timetable.html',   # ✅ correct
        student=student,
        student_class=student.current_class,
        time_ticks=time_ticks,
        day_blocks=day_blocks,
        vlines=vlines,
        col_template=col_template,
        total_minutes=total_minutes,
        download_ts=int(datetime.utcnow().timestamp())
    )

@parent_bp.route('/download_child_timetable/<int:child_id>')
@login_required
def download_child_timetable(child_id):
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from datetime import datetime
    from flask import send_file, flash, redirect, url_for

    # Make sure current user is a parent
    if current_user.role != 'parent':
        flash('Access denied.', 'danger')
        return redirect(url_for('parent.dashboard'))

    # Get child profile and class
    child_profile = StudentProfile.query.get(child_id)
    if not child_profile:
        flash('Child profile not found.', 'danger')
        return redirect(url_for('parent.dashboard'))

    # Check if this child belongs to the parent
    link = ParentChildLink.query.filter_by(parent_id=current_user.id, student_id=child_id).first()
    if not link:
        flash('You do not have permission to view this timetable.', 'danger')
        return redirect(url_for('parent.dashboard'))

    student_class = child_profile.current_class

    timetable_entries = TimetableEntry.query \
        .filter_by(assigned_class=student_class) \
        .join(Course, TimetableEntry.course_id == Course.id) \
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time) \
        .all()

    if not timetable_entries:
        flash('No timetable available to download.', 'warning')
        return redirect(url_for('parent.view_child_timetable', child_id=child_id))

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

    # PDF Paragraph style
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        'cell_style',
        parent=styles['Normal'],
        alignment=1,  # center
        fontSize=9,
        leading=10,
        wordWrap='CJK',
    )

    # Build timetable matrix
    timetable_matrix = []
    now = datetime.now()
    today_name = now.strftime('%A')

    for i, day in enumerate(days):
        row = [day]
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

    elements.append(Paragraph(f"<b>{child_profile.full_name} — Class Timetable: {student_class}</b>", styles['Title']))
    elements.append(Spacer(1, 12))

    table = Table(data, colWidths=col_widths, repeatRows=1)

    table_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4A90E2")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
    ])

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
                     download_name=f"{child_profile.full_name}_{student_class}_timetable.pdf",
                     mimetype='application/pdf')


