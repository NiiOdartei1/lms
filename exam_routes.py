from flask import Blueprint, current_app, render_template, abort, redirect, url_for, flash, jsonify, session, send_from_directory, send_file
from flask import request
from flask_login import login_required, current_user, login_user
from models import db, User, Quiz, StudentQuizSubmission, Question, StudentProfile, QuizAttempt, Assignment, CourseMaterial, StudentCourseRegistration, Course,  TimetableEntry, AcademicCalendar, AcademicYear, AppointmentSlot, AppointmentBooking, StudentFeeBalance, ClassFeeStructure, StudentFeeTransaction, Exam, ExamSubmission, ExamQuestion, ExamAttempt, ExamSet, ExamSetQuestion, Notification, NotificationRecipient
from datetime import date, datetime, timedelta, time
from sqlalchemy.orm import joinedload
from forms import ExamLoginForm   # adjust path depending on your project structure


exam_bp = Blueprint('exam', __name__, url_prefix='/exam')

# Welcome page
@exam_bp.route('/welcome')
def welcome():
    flash('Welcome! Please login to view your exams.', 'info')
    return render_template('exam/welcome.html')

@exam_bp.route('/login', methods=['GET', 'POST'])
def exam_login():
    form = ExamLoginForm()

    if form.validate_on_submit():
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        user = User.query.filter_by(user_id=user_id).first()
        if user and user.check_password(password):
            if user.role == 'student':  # Only students
                login_user(user)
                flash(f"Welcome back, {user.first_name}!", 'success')
                return redirect(url_for("exam.exam_dashboard"))  # <-- redirect to dashboard
            else:
                flash("Only students can log in here.", "danger")
                return redirect(url_for("exam.exam_login"))

        flash("Invalid login credentials.", "danger")

    return render_template("exam/login.html", form=form)

@exam_bp.route('/dashboard')
@login_required
def exam_dashboard():
    if current_user.role != 'student':
        flash("Only students can access exams.", "danger")
        return redirect(url_for("exam.exam_login"))

    exams = Exam.query.all()
    now = datetime.utcnow()

    # Prepare data for template
    exam_data = []
    for exam in exams:
        submission = ExamSubmission.query.filter_by(
            exam_id=exam.id,
            student_id=current_user.id
        ).first()
        status = 'Upcoming'
        if exam.start_datetime <= now <= exam.end_datetime:
            status = 'Ongoing'
        elif now > exam.end_datetime:
            status = 'Ended'

        exam_data.append({
            "exam": exam,
            "status": status,
            "attempted": bool(submission),
            "submission_id": submission.id if submission else None
        })

    return render_template('exam/dashboard.html', exams=exam_data)

# --- EXAMS ---
@exam_bp.route('/exams')
@login_required
def exams():
    exams = Exam.query.all()
    now = datetime.utcnow()  # or datetime.now() depending on your timezone handling

    # add a temporary 'status' attribute to each exam
    for exam in exams:
        if exam.start_datetime <= now <= exam.end_datetime:
            exam.status = 'Ongoing'
        elif now < exam.start_datetime:
            exam.status = 'Upcoming'
        else:
            exam.status = 'Ended'

    return render_template('exam/exams.html', exams=exams)

@exam_bp.route('/take-exam/<int:exam_id>/<int:attempt_id>')
@login_required
def take_exam(exam_id, attempt_id):
    if current_user.role != 'student':
        abort(403)

    exam = Exam.query.get_or_404(exam_id)
    now = datetime.utcnow()

    # check timing
    if now < exam.start_datetime:
        flash("This exam is not yet available.", "warning")
        return redirect(url_for('student.exams'))

    if now > exam.end_datetime:
        flash("This exam is closed.", "danger")
        return redirect(url_for('student.exams'))

    # get attempt record (with assigned set)
    attempt = ExamAttempt.query.filter_by(
        id=attempt_id,
        exam_id=exam.id,
        student_id=current_user.id
    ).first_or_404()

    if attempt.submitted:
        flash("You have already submitted this exam.", "danger")
        return redirect(url_for('student.exam_instructions', exam_id=exam.id, attempt_id=attempt.id))

    # ✅ Load questions from assigned set (if any)
    if attempt.set_id:
        set_questions = (
            db.session.query(ExamQuestion)
            .join(ExamSetQuestion, ExamSetQuestion.question_id == ExamQuestion.id)
            .filter(ExamSetQuestion.set_id == attempt.set_id)
            .options(joinedload(ExamQuestion.options))
            .order_by(ExamSetQuestion.order)
            .all()
        )
    else:
        # fallback: whole exam pool if no set assigned
        set_questions = exam.questions

    exam_data = {
        "id": exam.id,
        "title": exam.title,
        "duration_minutes": exam.duration_minutes,
        "start_datetime": exam.start_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "end_datetime": exam.end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "options": [{"id": opt.id, "text": opt.text} for opt in q.options]
            }
            for q in set_questions
        ]
    }

    return render_template(
        "exam/take_exam.html",
        exam_json=exam_data,
        session=session,
        attempt=attempt
    )

@exam_bp.route('/exams/<int:exam_id>/password', methods=['GET','POST'])
@login_required
def exam_password(exam_id):
    if current_user.role != 'student':
        abort(403)

    exam = Exam.query.get_or_404(exam_id)

    # ✅ First check if student manually selected a set
    selected_set_key = f'selected_set_for_exam_{exam.id}'
    chosen_set_obj = None
    if selected_set_key in session:
        chosen_set_obj = ExamSet.query.filter_by(
            id=session[selected_set_key], exam_id=exam.id
        ).first()

    # ✅ Otherwise fallback to auto-assignment logic
    if not chosen_set_obj:
        chosen_set_obj = pick_set_for_student(exam, current_user)

    if not chosen_set_obj:
        flash("No set assigned to you yet.", "danger")
        return redirect(url_for('exam.exams'))

    if request.method == 'POST':
        entered_password = request.form.get("set_password", "").strip()

        if chosen_set_obj.access_password != entered_password:
            flash("Incorrect password. Please try again.", "danger")
            return redirect(request.url)

        # ✅ Mark password as passed
        session[f'exam_{exam.id}_set_verified'] = True
        return redirect(url_for('exam.exam_instructions', exam_id=exam.id))

    return render_template("exam/exam_password.html", exam=exam, chosen_set=chosen_set_obj)

@exam_bp.route('/exams/<int:exam_id>/instructions', methods=['GET', 'POST'])
@login_required
def exam_instructions(exam_id):
    if current_user.role != 'student':
        abort(403)

    exam = Exam.query.get_or_404(exam_id)

    # ✅ Ensure password step was passed
    if not session.get(f'exam_{exam.id}_set_verified'):
        flash("You must enter the exam password first.", "warning")
        return redirect(url_for('exam.exam_password', exam_id=exam.id))

    # Check if student already submitted this exam
    submission = ExamSubmission.query.filter_by(
        exam_id=exam.id, student_id=current_user.id
    ).first()
    can_attempt = submission is None

    # Determine set to preview (after password validation, this is always defined)
    selected_set_key = f'selected_set_for_exam_{exam.id}'
    preview_set = None
    if selected_set_key in session:
        sel_id = session.get(selected_set_key)
        preview_set = ExamSet.query.filter_by(id=sel_id, exam_id=exam.id).first()
    else:
        preview_set = pick_set_for_student(exam, current_user)

    if request.method == 'POST':
        if not can_attempt:
            flash("You have already submitted this exam.", "warning")
            return redirect(url_for("exam.exams"))

        # Confirm chosen set
        chosen_set_obj = preview_set
        if not chosen_set_obj:
            flash("No set assigned to you.", "danger")
            return redirect(url_for("exam.exams"))

        # Create attempt
        new_attempt = ExamAttempt(
            exam_id=exam.id,
            set_id=chosen_set_obj.id,
            student_id=current_user.id
        )
        db.session.add(new_attempt)
        db.session.commit()

        # Clear verification so they can’t restart without password
        session.pop(f'exam_{exam.id}_set_verified', None)

        return redirect(url_for("exam.take_exam",
                               exam_id=exam.id,
                               attempt_id=new_attempt.id))

    return render_template(
        "exam/exam_instructions.html",
        exam=exam,
        can_attempt=can_attempt,
        preview_set=preview_set
    )

from hashlib import sha256
import random
from flask import session

def pick_set_for_student(exam, student_user):
    """
    Return an ExamSet object according to exam.assignment_mode.
    NOTE: does NOT persist assignment (except for deterministic hash which is stable).
    """
    sets = ExamSet.query.filter_by(exam_id=exam.id).all()
    if not sets:
        return None

    mode = (exam.assignment_mode or 'random')

    if mode == 'random':
        # preview: random choice (not persisted). The actual persisted pick is created when student starts.
        return random.choice(sets)

    if mode == 'hash':
        # deterministic mapping by hashing student id + optional seed
        seed = (exam.assignment_seed or '') + (student_user.user_id or str(student_user.id))
        h = sha256(seed.encode()).hexdigest()
        idx = int(h, 16) % len(sets)
        return sets[idx]

    if mode == 'choice':
        # no automatic pick — let student choose (return None to indicate choice required)
        return None

    return random.choice(sets)


@exam_bp.route('/exams/<int:exam_id>/select-set', methods=['GET','POST'])
@login_required
def select_exam_set(exam_id):
    if current_user.role != 'student':
        abort(403)

    exam = Exam.query.get_or_404(exam_id)
    if exam.assignment_mode != 'choice':
        flash("This exam does not allow selecting a set.", "warning")
        return redirect(url_for('exam.exams'))

    sets = ExamSet.query.filter_by(exam_id=exam.id).order_by(ExamSet.name).all()
    if not sets:
        flash("No sets available for this exam.", "danger")
        return redirect(url_for('exam.exams'))

    if request.method == 'POST':
        selected_set_id = request.form.get('set_id')
        try:
            selected_set_id = int(selected_set_id)
        except (TypeError, ValueError):
            flash("Please select a valid set.", "danger")
            return redirect(request.url)

        selected_set = ExamSet.query.filter_by(id=selected_set_id, exam_id=exam.id).first()
        if not selected_set:
            flash("Invalid set selection.", "danger")
            return redirect(request.url)

        # ✅ Save selected set in session
        session[f'selected_set_for_exam_{exam.id}'] = selected_set.id
        flash(f"Set '{selected_set.name}' selected — enter the password to continue.", "success")

        # ✅ Always redirect to password page
        return redirect(url_for('exam.exam_password', exam_id=exam.id))

    return render_template('exam/select_set.html', exam=exam, sets=sets)

@exam_bp.route('/start-exam-timer/<int:exam_id>', methods=['POST'])
@login_required
def start_exam_timer(exam_id):
    key = f'exam_{exam_id}_start_time'
    if key not in session:
        session[key] = datetime.utcnow().isoformat()
        session.modified = True
    return jsonify({'status': 'started'})

@exam_bp.route('/autosave_exam_answer', methods=['POST'])
@login_required
def autosave_exam_answer():
    data = request.get_json()
    exam_id = data.get('exam_id')
    question_id = str(data.get('question_id'))
    selected_option_id = str(data.get('selected_option_id'))

    if not all([exam_id, question_id, selected_option_id]):
        return jsonify({'error': 'Incomplete data'}), 400

    session_key = f'autosaved_exam_{exam_id}_{current_user.user_id}'
    if session_key not in session:
        session[session_key] = {}

    session[session_key][question_id] = selected_option_id
    session.modified = True
    return jsonify({'status': 'saved'})


@exam_bp.route('/submit_exam/<int:exam_id>', methods=['POST'])
@login_required
def submit_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)

    # ✅ check if this student already has a submission
    existing = ExamSubmission.query.filter_by(
        exam_id=exam.id, student_id=current_user.id
    ).first()

    if existing:
        flash("You have already submitted this exam. Only one submission is allowed.", "warning")
        return redirect(url_for('exam.exam_result', submission_id=existing.id))

    autosaved_key = f'autosaved_exam_{exam.id}_{current_user.user_id}'
    autosaved_answers = session.get(autosaved_key, {})

    score = 0
    for q in exam.questions:
        submitted_option_id = request.form.get(f"answers[{q.id}]")
        if not submitted_option_id:
            submitted_option_id = autosaved_answers.get(str(q.id))

        if submitted_option_id:
            try:
                submitted_option_id = int(submitted_option_id)
                correct_option = next((opt for opt in q.options if opt.is_correct), None)
                if correct_option and submitted_option_id == correct_option.id:
                    score += q.marks
            except (ValueError, TypeError):
                continue

    submission = ExamSubmission(
        student_id=current_user.id,
        exam_id=exam.id,
        score=score,
        submitted_at=datetime.utcnow()
    )
    db.session.add(submission)

    attempt = ExamAttempt(
        student_id=current_user.id,
        exam_id=exam.id,
        score=score,
        submitted_at=datetime.utcnow()
    )
    db.session.add(attempt)

    session.pop(autosaved_key, None)
    session.pop(f'exam_{exam.id}_start_time', None)

    db.session.commit()
    return redirect(url_for('exam.exam_result', submission_id=submission.id))

@exam_bp.route('/has-submitted-exam/<int:exam_id>')
@login_required
def has_submitted_exam(exam_id):
    exists = ExamSubmission.query.filter_by(
        student_id=current_user.id,
        exam_id=exam_id
    ).first()
    return jsonify({"submitted": bool(exists)})

@exam_bp.route('/exam_result/<int:submission_id>')
@login_required
def exam_result(submission_id):
    submission = ExamSubmission.query.get_or_404(submission_id)

    # Security check
    if current_user.role == 'student':
        if submission.student_id != current_user.id:
            abort(403)
    elif current_user.role == 'teacher':
        # optional: restrict by teacher's assigned classes
        if submission.student.class_id not in current_user.classes_assigned:
            abort(403)
    # admins can view everything

    exam = submission.exam
    set_name = None
    max_score = 0

    if submission.set_id:
        exam_set = ExamSet.query.filter_by(id=submission.set_id, exam_id=exam.id).first()
        if not exam_set:
            abort(404, description="Exam set not found")
        set_name = exam_set.name
        max_score = exam_set.computed_max_score
    else:
        max_score = sum((q.marks or 0) for q in exam.questions)

    max_score = float(max_score or 0)
    pass_percent = getattr(exam, "pass_percent", 0.5)

    return render_template(
        "exam/exam_result.html",
        exam=exam,
        submission=submission,
        max_score=max_score,
        set_name=set_name,
        pass_percent=pass_percent,
    )
