from flask import Blueprint, render_template, abort, flash, redirect, url_for, request, send_file, current_app, jsonify
from flask_login import login_required, current_user, login_user
from forms import ChangePasswordForm, ParentLoginForm
from models import User, ParentProfile, ParentChildLink, StudentProfile, Assignment, StudentQuizSubmission, Quiz, AttendanceRecord, StudentFeeBalance, StudentFeeTransaction , ClassFeeStructure , Notification, NotificationRecipient
from datetime import datetime
import os
from werkzeug.utils import secure_filename

parent_bp = Blueprint('parent', __name__, url_prefix='/parent')


@parent_bp.route('/login', methods=['GET', 'POST'])
def parent_login():
    form = ParentLoginForm()
    if form.validate_on_submit():
        user_id = form.user_id.data.strip()
        username = form.username.data.strip()
        password = form.password.data.strip()

        # First, try by user_id and role
        user = User.query.filter_by(user_id=user_id, role='parent').first()

        # If not found, try by username (case-insensitive)
        if not user:
            user = User.query.filter(User.username.ilike(username), User.role == 'parent').first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for('parent.dashboard'))

        flash("Invalid parent credentials. Make sure you use your assigned username and ID.", "danger")

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
        # more robust join: return (StudentProfile, User) tuples
        children = (
            db.session.query(StudentProfile, User)
            .join(ParentChildLink, ParentChildLink.student_id == StudentProfile.id)
            .join(User, StudentProfile.user_id == User.user_id)
            .filter(ParentChildLink.parent_id == parent_profile.id)
            .all()
        )

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


