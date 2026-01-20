import logging
from flask import Blueprint, app, current_app, render_template, abort, request, redirect, url_for, flash, jsonify, session, send_from_directory
from flask_login import login_required, current_user, login_user
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from admissions.models import AdmissionVoucher, Application
from models import PasswordResetRequest, PasswordResetToken, StudentFeeBalance, db, User, Admin, StudentProfile, ParentProfile, Quiz, Question, Option, StudentQuizSubmission, Assignment, CourseMaterial, Course, CourseLimit, TimetableEntry, TeacherProfile, AcademicCalendar, AcademicYear, ClassFeeStructure, StudentFeeTransaction, ParentChildLink, Exam, ExamSubmission, ExamQuestion, ExamAttempt, ExamOption, ExamSet, ExamSetQuestion, SchoolClass
from datetime import date, datetime, timedelta, time
from sqlalchemy import extract, asc, desc
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import os, json, csv, re, string, random
from sqlalchemy import func
from forms import AdminLoginForm, QuizForm, AdminRegisterForm, AssignmentForm, MaterialForm, CourseForm, CourseLimitForm, ExamForm, ExamSetForm, ExamQuestionForm
from utils.promotion import promote_student
from utils.score import calculate_student_score
from utils.backup import generate_quiz_csv_backup, backup_students_to_csv
from utils.serializers import (serialize_admin, serialize_submission, serialize_user, serialize_student, serialize_quiz, serialize_question, serialize_option, serialize_submission)
from utils.receipts import generate_receipt  # ✅ import the receipt generator
from utils.email import send_approval_credentials_email, send_email, send_temporary_password_email, send_password_reset_email
from utils.notifications import create_assignment_notification, create_fee_notification
import uuid, secrets
from zipfile import ZipFile
import tempfile

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

UPLOAD_FOLDER = 'static/uploads/quizzes'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_admin_or_teacher():
    return getattr(current_user, 'role', None) in ['admin', 'teacher']

@admin_bp.route('/get_courses/<assigned_class>')
@login_required
def get_courses(assigned_class):
    courses = Course.query.filter(func.lower(Course.assigned_class) == assigned_class.lower()).all()
    return jsonify([{"id": c.id, "name": c.name} for c in courses])

@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    form = AdminLoginForm()
    next_page = request.args.get('next')

    if form.validate_on_submit():
        username = form.username.data.strip()
        admin_id = form.user_id.data.strip()
        password = form.password.data.strip()

        admin = Admin.query.filter_by(admin_id=admin_id).first()

        if admin and admin.username.lower() == username.lower() and admin.check_password(password):
            login_user(admin)
            flash(f"Welcome back, Admin {admin.username}!", "success")
            return redirect(next_page or url_for("admin.dashboard"))

        flash("Invalid admin login credentials.", "danger")
        return render_template("admin/login.html", form=form), 401  

    return render_template("admin/login.html", form=form)

#--------------- Admin Dashboard ---------------
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'admin':
        abort(403)

    student_count = User.query.filter_by(role='student').count()
    teacher_count = User.query.filter_by(role='teacher').count()
    parent_count = User.query.filter_by(role='parent').count()
    admin_count = User.query.filter_by(role='admin').count()

    users = User.query.order_by(User.id.desc()).limit(10).all()  # recent users

    return render_template(
        'admin/admin_dashboard.html',
        user=current_user,
        users=users,
        student_count=student_count,
        teacher_count=teacher_count,
        parent_count=parent_count,
        admin_count=admin_count
    )

# --------------- User Registration ---------------
@admin_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register_user():
    # Only allow admins
    if getattr(current_user, 'role', None) != 'admin':
        abort(403)

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        middle_name = request.form.get('middle_name', '').strip()
        role = request.form.get('role', '').strip().lower()
        temp_password = request.form.get('password', '').strip()

        if not (first_name and last_name and role and temp_password):
            flash("First name, last name, role, and password are required.", 'danger')
            return redirect(url_for('admin.register_user'))

        picture = request.files.get('profile_picture')
        profile_picture = None

        if picture and picture.filename != '':
            filename = secure_filename(picture.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            picture_path = os.path.join(current_app.config['PROFILE_PICS_FOLDER'], unique_filename)

            os.makedirs(current_app.config['PROFILE_PICS_FOLDER'], exist_ok=True)
            picture.save(picture_path)

            profile_picture = unique_filename
        else:
            profile_picture = "default_avatar.png"

        email = (request.form.get('email') or
                 request.form.get('parent_email') or
                 request.form.get('user_email') or
                 '').strip() or None

        if email:
            existing_email_user = User.query.filter(User.email == email).first()
            if existing_email_user:
                flash("That email is already in use by another account.", "danger")
                return redirect(url_for('admin.register_user'))

        username = request.form.get('username')
        if not username:
            username = generate_unique_username(first_name, middle_name, last_name, role)

        prefix_map = {'student': 'STD', 'teacher': 'TCH', 'parent': 'PAR'}
        prefix = prefix_map.get(role.lower(), 'GEN')

        base_count = User.query.filter_by(role=role).count() + 1
        count = base_count
        while True:
            user_id = f"{prefix}{count:03d}"
            if not User.query.filter_by(user_id=user_id).first():
                break
            count += 1

        if User.query.filter_by(username=username).first():
            flash("Generated username already exists—please try again.", 'danger')
            return redirect(url_for('admin.register_user'))

        new_user = User(
            user_id=user_id,
            username=username,
            email=email,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            role=role,
            profile_picture=profile_picture
        )
        new_user.set_password(temp_password)
        db.session.add(new_user)

        try:
            if role == 'student':
                dob_str = request.form.get('dob', '').strip()
                dob = datetime.strptime(dob_str, '%Y-%m-%d') if dob_str else None
                student_profile = StudentProfile(
                    user_id=user_id,
                    dob=dob,
                    gender=request.form.get('gender', '').strip(),
                    nationality=request.form.get('nationality', '').strip(),
                    religion=request.form.get('religion', '').strip(),
                    address=request.form.get('address', '').strip(),
                    city=request.form.get('city', '').strip(),
                    state=request.form.get('state', '').strip(),
                    postal_code=request.form.get('postal_code', '').strip(),
                    phone=request.form.get('phone', '').strip(),
                    email=(request.form.get('email') or '').strip(),
                    guardian_name=request.form.get('guardian_name', '').strip(),
                    guardian_relation=request.form.get('guardian_relation', '').strip(),
                    guardian_contact=request.form.get('guardian_contact', '').strip(),
                    previous_school=request.form.get('previous_school', '').strip(),
                    last_class_completed=request.form.get('last_class_completed', '').strip(),
                    academic_performance=request.form.get('academic_performance', '').strip(),
                    current_class=request.form.get('current_class', '').strip(),
                    academic_year=request.form.get('academic_year', '').strip(),
                    preferred_second_language=request.form.get('preferred_second_language', '').strip(),
                    sibling_name=request.form.get('sibling_name', '').strip(),
                    sibling_class=request.form.get('sibling_class', '').strip(),
                    blood_group=request.form.get('blood_group', '').strip(),
                    medical_conditions=request.form.get('medical_conditions', '').strip(),
                    emergency_contact_name=request.form.get('emergency_contact_name', '').strip(),
                    emergency_contact_number=request.form.get('emergency_contact_number', '').strip()
                )
                db.session.add(student_profile)

            elif role == 'teacher':
                date_of_hire_str = request.form.get('date_of_hire', '').strip()
                date_of_hire = datetime.strptime(date_of_hire_str, '%Y-%m-%d') if date_of_hire_str else None
                teacher_profile = TeacherProfile(
                    user_id=user_id,
                    employee_id=request.form.get('employee_id', '').strip(),
                    dob=datetime.strptime(request.form.get('teacher_dob', '').strip(), '%Y-%m-%d') if request.form.get('teacher_dob') else None,
                    gender=request.form.get('teacher_gender', '').strip(),
                    nationality=request.form.get('teacher_nationality', '').strip(),
                    qualification=request.form.get('qualification', '').strip(),
                    specialization=request.form.get('specialization', '').strip(),
                    years_of_experience=int(request.form.get('years_of_experience') or 0),
                    subjects_taught=request.form.get('subjects_taught', '').strip(),
                    employment_type=request.form.get('employment_type', '').strip(),
                    department=request.form.get('department', '').strip(),
                    date_of_hire=date_of_hire,
                    office_location=request.form.get('office_location', '').strip()
                )
                db.session.add(teacher_profile)

            elif role == 'parent':
                dob_str = request.form.get('parent_dob', '').strip()
                dob = datetime.strptime(dob_str, '%Y-%m-%d') if dob_str else None
                parent_profile = ParentProfile(
                    user_id=user_id,
                    dob=dob,
                    gender=request.form.get('parent_gender', '').strip(),
                    nationality=request.form.get('parent_nationality', '').strip(),
                    occupation=request.form.get('occupation', '').strip(),
                    education_level=request.form.get('education_level', '').strip(),
                    phone_number=request.form.get('phone_number', '').strip(),
                    email=(request.form.get('parent_email') or '').strip(),
                    address=request.form.get('parent_address', '').strip(),
                    relationship_to_student=request.form.get('relationship_to_student', '').strip(),
                    number_of_children=int(request.form.get('number_of_children') or 0),
                    emergency_contact_name=request.form.get('emergency_contact_name', '').strip(),
                    emergency_contact_phone=request.form.get('emergency_contact_phone', '').strip(),
                    preferred_contact_method=request.form.get('preferred_contact_method', '').strip()
                )
                db.session.add(parent_profile)
                db.session.flush()

                child_ids = request.form.getlist('child_student_ids')
                for sid in child_ids:
                    if sid:
                        db.session.add(ParentChildLink(parent_id=parent_profile.id, student_id=int(sid)))

            db.session.commit()
            flash(f"{role.title()} '{first_name} {last_name}' registered successfully! Username: {username}", "success")
            return redirect(url_for('admin.dashboard'))

        except IntegrityError:
            db.session.rollback()
            flash("A database integrity error occurred (duplicate user/email). Please try again with different data.", "danger")
            return redirect(url_for('admin.register_user'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error saving user: {e}", "danger")
            return redirect(url_for('admin.register_user'))

    students = StudentProfile.query.join(User).order_by(User.first_name).all()
    classes = db.session.query(StudentProfile.current_class).distinct().order_by(StudentProfile.current_class).all()
    classes = [c[0] for c in classes if c[0]]

    return render_template(
        'admin/register_user.html',
        form=AdminRegisterForm(),
        students=students,
        classes=classes
    )

@admin_bp.route('/get-students-by-class/<class_name>')
@login_required
def get_students_by_class(class_name):
    if getattr(current_user, 'role', None) != 'admin':
        abort(403)

    students = (
        StudentProfile.query
        .join(User)
        .filter(StudentProfile.current_class == class_name)
        .order_by(User.first_name)
        .all()
    )

    return jsonify({
        "students": [
            {"id": s.id, "name": s.user.full_name if hasattr(s, 'user') else (getattr(s, 'full_name', f'Student #{s.id}'))}
            for s in students
        ]
    })


def generate_unique_username(first_name, middle_name, last_name, role):
    first_initial = first_name[0].lower() if first_name else ''
    middle_initial = middle_name[0].lower() if middle_name else ''
    surname_part = last_name.lower()

    base_username = f"{first_initial}{middle_initial}{surname_part}"

    domain_map = {
        'student': 'st.knust.edu.gh',
        'teacher': 'tch.knust.edu.gh',
        'parent': 'par.knust.edu.gh'
    }
    domain = domain_map.get(role, 'knust.edu.gh')

    full_username = f"{base_username}@{domain}"

    counter = 1
    unique_username = full_username
    while User.query.filter_by(username=unique_username).first():
        unique_username = f"{base_username}{counter}@{domain}"
        counter += 1

    return unique_username

@admin_bp.route('/generate-username', methods=['POST'])
@login_required
def generate_username():
    data = request.get_json()
    first = data.get('first_name', '').strip()
    middle = data.get('middle_name', '').strip()
    last = data.get('last_name', '').strip()
    role = data.get('role', '').strip()

    if not (first and last and role):
        return jsonify({'error': 'Missing required fields'}), 400

    username = generate_unique_username(first, middle, last, role)

    return jsonify({'username': username})

def generate_random_password(length=8):
    chars = string.ascii_letters + string.digits + '!@#$%^&*()'
    return ''.join(random.choices(chars, k=length))

@admin_bp.route('/generate-passwords')
@login_required
def generate_passwords():
    passwords = [generate_random_password() for _ in range(3)]
    return jsonify({'passwords': passwords})

#--------------- Student Management ---------------
@admin_bp.route('/students')
@login_required
def view_students():
    students = User.query.filter_by(role='student').join(StudentProfile).all()
    return render_template('admin/view_students.html', students=students)

@admin_bp.route('/quizzes')
def manage_quizzes():
    quizzes = Quiz.query.order_by(Quiz.start_datetime.desc()).all()
    now = datetime.utcnow()

    upcoming = [q for q in quizzes if q.start_datetime > now]
    ongoing = [q for q in quizzes if q.start_datetime <= now <= q.end_datetime]
    past = [q for q in quizzes if q.end_datetime < now]

    return render_template(
        'admin/manage_quizzes.html',
        quizzes=quizzes,
        now=now,
        upcoming_count=len(upcoming),
        ongoing_count=len(ongoing),
        past_count=len(past)
    )

@admin_bp.route('/edit/<model>/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_record(model, record_id):
    if model == 'parents':
        parent = ParentProfile.query.get_or_404(record_id)
    elif model == 'students':
        record = StudentProfile.query.get_or_404(record_id)
    else:
        abort(404)

    classes = get_class_choices()

    if request.method == 'POST':
        if model == 'parents':
            # Get list of student ids submitted from form (hidden inputs)
            # Accept both 'child_student_ids[]' and 'child_student_ids' name variants
            raw_ids = request.form.getlist('child_student_ids[]') or request.form.getlist('child_student_ids')
            # Normalize to ints and filter invalid values
            student_ids = []
            for v in raw_ids:
                if not v:
                    continue
                try:
                    student_ids.append(int(v))
                except ValueError:
                    continue

            db.session.query(ParentChildLink).filter_by(parent_id=parent.id).delete(synchronize_session=False)

            for sid in student_ids:
                student = StudentProfile.query.get(sid)
                if student:
                    link = ParentChildLink(parent_id=parent.id, student_id=sid)
                    db.session.add(link)

            db.session.commit()
            flash("Parent's children updated.", "success")
            return redirect(url_for('admin.view_database', model='parents'))

        else:
            for key, value in request.form.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            db.session.commit()
            flash(f"{model.capitalize()} updated successfully.", "success")
            return redirect(url_for('admin.list_records', model=model))

    if model == 'parents':
        return render_template('admin/edit_parent_children.html', parent=parent, classes=classes, model=model)
    else:
        return render_template('admin/edit_parent_children.html', record=record, model=model)


def generate_quiz_backup_file(quiz_data, questions_data, backup_dir='quiz_backups'):
    os.makedirs(backup_dir, exist_ok=True)

    filename_base = f"{quiz_data['title'].replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    json_path = os.path.join(backup_dir, f"{filename_base}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'quiz': quiz_data, 'questions': questions_data}, f, indent=4)

    csv_path = os.path.join(backup_dir, f"{filename_base}.csv")
    with open(csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['Question', 'Option', 'Is Correct'])

        for question in questions_data:
            q_text = question['text']
            for opt in question['options']:
                writer.writerow([q_text, opt['text'], 'TRUE' if opt['is_correct'] else 'FALSE'])

    return json_path  # or return both paths if needed

@admin_bp.route('/add_quiz', methods=['GET', 'POST'])
@login_required
def add_quiz():
    admin_only()

    form = QuizForm()
    form.assigned_class.choices = get_class_choices()

    selected_class = request.form.get('assigned_class') or form.assigned_class.data
    if selected_class:
        form.course_name.choices = get_course_choices(selected_class)
    else:
        form.course_name.choices = []

    if not form.validate_on_submit():
        return render_template('admin/add_quiz.html', form=form)

    try:
        # BASIC FIELDS
        assigned_class = form.assigned_class.data
        title = form.title.data.strip()
        start_datetime = form.start_datetime.data
        end_datetime = form.end_datetime.data
        duration = int(form.duration.data)
        attempts_allowed = form.attempts_allowed.data

        # COURSE (CRITICAL FIX)
        course_id = request.form.get('course_id', type=int)
        if not course_id:
            flash("Please select a valid course.", "danger")
            return redirect(request.url)

        course = Course.query.get(course_id)
        if not course:
            flash("Selected course does not exist.", "danger")
            return redirect(request.url)

        # DUPLICATE TITLE CHECK FIX
        if Quiz.query.filter_by(title=title, course_id=course.id, assigned_class=assigned_class).first():
            flash("A quiz with this title already exists for this course and class.", "danger")
            return redirect(request.url)

        # TIME OVERLAP CHECK
        overlap = Quiz.query.filter(
            Quiz.assigned_class == assigned_class,
            Quiz.start_datetime < end_datetime,
            Quiz.end_datetime > start_datetime
        ).first()

        if overlap:
            flash("Another quiz is already scheduled during this time.", "danger")
            return redirect(request.url)

        # CREATE QUIZ
        quiz = Quiz(
            assigned_class=assigned_class,
            course_id=course.id,
            course_name=course.name,
            title=title,
            date=start_datetime.date(),
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            duration_minutes=duration,
            attempts_allowed=attempts_allowed
        )

        # FILE UPLOAD
        content_file = request.files.get('content_file')
        if content_file and content_file.filename and allowed_file(content_file.filename):
            filename = secure_filename(content_file.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            content_file.save(os.path.join(UPLOAD_FOLDER, filename))
            quiz.content_file = filename

        db.session.add(quiz)
        db.session.flush()  # get quiz.id safely

        # SAVE QUESTIONS
        for key in request.form:
            if not re.match(r'^questions\[\d+\]\[text\]$', key):
                continue

            q_index = key.split('[')[1].split(']')[0]
            question_text = request.form.get(key, '').strip()
            if not question_text:
                continue

            blanks = re.findall(r'_{3,}', question_text)
            q_type = 'fill_in' if blanks else request.form.get(
                f'questions[{q_index}][type]', 'mcq'
            )

            question = Question(
                quiz_id=quiz.id,
                text=question_text,
                question_type=q_type
            )
            db.session.add(question)
            db.session.flush()

            # MULTIPLE CHOICE
            if q_type == 'mcq':
                o_index = 0
                while True:
                    text_key = f'questions[{q_index}][options][{o_index}][text]'
                    correct_key = f'questions[{q_index}][options][{o_index}][is_correct]'

                    if text_key not in request.form:
                        break

                    opt_text = request.form.get(text_key, '').strip()
                    if opt_text:
                        db.session.add(Option(
                            question_id=question.id,
                            text=opt_text,
                            is_correct=(correct_key in request.form)
                        ))
                    o_index += 1

            # FILL IN THE BLANK
            elif q_type == 'fill_in':
                a_index = 0
                while True:
                    ans_key = f'questions[{q_index}][answers][{a_index}]'
                    if ans_key not in request.form:
                        break

                    ans = request.form.get(ans_key, '').strip()
                    if ans:
                        db.session.add(Option(
                            question_id=question.id,
                            text=ans,
                            is_correct=True
                        ))
                    a_index += 1

        db.session.commit()
        flash("Quiz created successfully!", "success")
        return redirect(url_for('admin.manage_quizzes'))

    except Exception as e:
        db.session.rollback()
        flash(f"Error saving quiz: {e}", "danger")
        return redirect(request.url)

def is_quiz_active(quiz):
    now = datetime.now()
    quiz_start = datetime.combine(quiz.date, quiz.start_time)
    quiz_end = quiz_start + timedelta(minutes=quiz.duration_minutes)
    return quiz_start <= now <= quiz_end

@admin_bp.route('/edit_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def edit_quiz(quiz_id):
    admin_only()

    quiz = Quiz.query.get_or_404(quiz_id)
    form = QuizForm(obj=quiz)

    # FORM CHOICES (SAME AS ADD)
    form.assigned_class.choices = get_class_choices()

    selected_class = request.form.get('assigned_class') or quiz.assigned_class
    if selected_class:
        form.course_name.choices = get_course_choices(selected_class)
    else:
        form.course_name.choices = []

    # HELPER: BUILD QUESTIONS
    def build_quiz_questions_payload(qz):
        payload = []
        for q in qz.questions:
            payload.append({
                "text": q.text,
                "type": q.question_type,
                "options": [
                    {"text": o.text, "is_correct": bool(o.is_correct)}
                    for o in q.options
                ]
            })
        return payload

    # GET
    if request.method == 'GET':
        form.course_id.data = quiz.course_id
        form.course_name.data = quiz.course_name

        return render_template(
            'admin/edit_quiz.html',
            form=form,
            quiz=quiz,
            quiz_questions=build_quiz_questions_payload(quiz),
            selected_course_id=quiz.course_id   # 🔥 ADD THIS
        )

    # POST (VALIDATION SAME AS ADD)
    if not form.validate_on_submit():
        return render_template(
            'admin/edit_quiz.html',
            form=form,
            quiz=quiz,
            quiz_questions=build_quiz_questions_payload(quiz)
        )

    try:
        # BASIC FIELDS
        assigned_class = form.assigned_class.data
        title = form.title.data.strip()
        start_datetime = form.start_datetime.data
        end_datetime = form.end_datetime.data
        duration = int(form.duration.data)
        attempts_allowed = form.attempts_allowed.data

        if end_datetime <= start_datetime:
            flash("Invalid start and end time.", "danger")
            return redirect(request.url)

        # COURSE (EXACT SAME AS ADD)
        course_id = request.form.get('course_id', type=int)
        if not course_id:
            flash("Please select a valid course.", "danger")
            return redirect(request.url)

        course = Course.query.get(course_id)
        if not course:
            flash("Selected course does not exist.", "danger")
            return redirect(request.url)

        # DUPLICATE TITLE CHECK
        if Quiz.query.filter(
            Quiz.id != quiz.id,
            Quiz.title == title,
            Quiz.course_id == course.id,
            Quiz.assigned_class == assigned_class
        ).first():
            flash("A quiz with this title already exists for this course and class.", "danger")
            return redirect(request.url)

        # TIME OVERLAP CHECK
        overlap = Quiz.query.filter(
            Quiz.id != quiz.id,
            Quiz.assigned_class == assigned_class,
            Quiz.start_datetime < end_datetime,
            Quiz.end_datetime > start_datetime
        ).first()

        if overlap:
            flash("Another quiz is already scheduled during this time.", "danger")
            return redirect(request.url)

        # UPDATE QUIZ (PARALLELS CREATE)
        quiz.assigned_class = assigned_class
        quiz.course_id = course.id
        quiz.course_name = course.name
        quiz.title = title
        quiz.start_datetime = start_datetime
        quiz.end_datetime = end_datetime
        quiz.date = start_datetime.date()
        quiz.duration_minutes = duration
        quiz.attempts_allowed = attempts_allowed

        # FILE UPLOAD
        content_file = request.files.get('content_file')
        if content_file and content_file.filename and allowed_file(content_file.filename):
            filename = secure_filename(content_file.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            content_file.save(os.path.join(UPLOAD_FOLDER, filename))
            quiz.content_file = filename

        # DELETE OLD QUESTIONS
        for q in quiz.questions:
            Option.query.filter_by(question_id=q.id).delete()
        Question.query.filter_by(quiz_id=quiz.id).delete()
        db.session.flush()

        # REBUILD QUESTIONS (IDENTICAL TO ADD)
        for key in request.form:
            if not re.match(r'^questions\[\d+\]\[text\]$', key):
                continue

            q_index = key.split('[')[1].split(']')[0]
            q_text = request.form.get(key, '').strip()
            if not q_text:
                continue

            blanks = re.findall(r'_{3,}', q_text)
            q_type = 'fill_in' if blanks else request.form.get(
                f'questions[{q_index}][type]', 'mcq'
            )

            question = Question(
                quiz_id=quiz.id,
                text=q_text,
                question_type=q_type
            )
            db.session.add(question)
            db.session.flush()

            if q_type == 'mcq':
                o_index = 0
                while True:
                    t_key = f'questions[{q_index}][options][{o_index}][text]'
                    c_key = f'questions[{q_index}][options][{o_index}][is_correct]'
                    if t_key not in request.form:
                        break

                    text = request.form.get(t_key, '').strip()
                    if text:
                        db.session.add(Option(
                            question_id=question.id,
                            text=text,
                            is_correct=(c_key in request.form)
                        ))
                    o_index += 1

            elif q_type == 'fill_in':
                a_index = 0
                while True:
                    a_key = f'questions[{q_index}][answers][{a_index}]'
                    if a_key not in request.form:
                        break

                    ans = request.form.get(a_key, '').strip()
                    if ans:
                        db.session.add(Option(
                            question_id=question.id,
                            text=ans,
                            is_correct=True
                        ))
                    a_index += 1

        db.session.commit()
        flash("Quiz updated successfully!", "success")
        return redirect(url_for('admin.manage_quizzes'))

    except Exception as e:
        db.session.rollback()
        flash(f"Error updating quiz: {e}", "danger")
        return redirect(request.url)

@admin_bp.route('/quizzes/delete/<int:quiz_id>', methods=['POST'])
@login_required
def delete_quiz(quiz_id):
    admin_only()
    quiz = Quiz.query.get_or_404(quiz_id)
    db.session.delete(quiz)
    db.session.commit()
    flash("Quiz deleted successfully.", "success")
    return redirect(url_for('admin.manage_quizzes'))

@admin_bp.route('/restore_quiz', methods=['GET', 'POST'])
@login_required
def restore_quiz():
    admin_only()
    if request.method == 'POST':
        file = request.files.get('backup_file')
        if not file or not file.filename.endswith('.json'):
            flash("Please upload a valid JSON backup file.", "danger")
            return redirect(request.url)

        try:
            data = json.load(file)
            quiz_data = data.get('quiz')
            questions_data = data.get('questions', [])

            # Prevent duplicate
            if Quiz.query.filter_by(title=quiz_data['title'], assigned_class=quiz_data['assigned_class']).first():
                flash("A quiz with this title already exists.", "danger")
                return redirect(request.url)

            course = Course.query.filter_by(name=quiz_data['course_name']).first()
            if not course:
                flash("Course from backup does not exist.", "danger")
                return redirect(request.url)

            quiz = Quiz(
                course_id=course.id,
                course_name=quiz_data['course_name'],
                title=quiz_data['title'],
                assigned_class=quiz_data['assigned_class'],
                start_datetime=datetime.fromisoformat(quiz_data['start_datetime']),
                end_datetime=datetime.fromisoformat(quiz_data['end_datetime']),
                duration_minutes=int(quiz_data['duration_minutes']),
                attempts_allowed=int(quiz_data['attempts_allowed']),
                content_file=quiz_data.get('content_file')
            )
            db.session.add(quiz)
            db.session.flush()

            for q in questions_data:
                blanks = re.findall(r'_{3,}', q['text'])
                q_type = 'fill_in' if blanks else q.get('question_type', 'mcq')
                question = Question(quiz_id=quiz.id, text=q['text'], question_type=q_type)
                db.session.add(question)
                db.session.flush()
                for opt in q.get('options', []):
                    db.session.add(Option(question_id=question.id, text=opt['text'], is_correct=opt['is_correct']))

            db.session.commit()
            flash("Quiz restored successfully from backup.", "success")
            return redirect(url_for('admin.manage_quizzes'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error restoring quiz: {e}", "danger")
            return redirect(request.url)

    return render_template("admin/restore_quiz.html")

#--------------- Exam and Event Management ---------------
# Admin Exam Management
@admin_bp.route('/exams')
@login_required
def manage_exams():
    exams = Exam.query.order_by(Exam.start_datetime.desc()).all()
    return render_template('admin/manage_exams.html', exams=exams)

def admin_only():
    if getattr(current_user, 'role', None) != 'admin':
        abort(403)

# 1. List sets & question pool for an exam
@admin_bp.route('/exam/<int:exam_id>/sets', methods=['GET'])
@login_required
def exam_sets(exam_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)

    pool_questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.id).all()

    sets = ExamSet.query.filter_by(exam_id=exam.id).order_by(ExamSet.id).all()

    set_q_map = {}
    for s in sets:
        set_q_map[s.id] = [sq.question_id for sq in s.set_questions]

    return render_template(
        'admin/exam_sets.html',
        exam=exam,
        pool_questions=pool_questions,
        sets=sets,
        set_q_map=set_q_map
    )

# 2. Create a new set for exam
@admin_bp.route('/exam/<int:exam_id>/sets/create', methods=['GET', 'POST'])
@login_required
def create_exam_set(exam_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    form = ExamSetForm()

    if form.validate_on_submit():
        try:
            name = form.name.data.strip()
            password = form.access_password.data.strip()

            new_set = ExamSet(
                name=name,
                exam_id=exam.id,
                access_password=password   # ✅ save the password
            )
            db.session.add(new_set)
            db.session.commit()
            flash(f"Set '{name}' created.", "success")
            return redirect(url_for('admin.exam_sets', exam_id=exam.id))

        except Exception as e:
            current_app.logger.exception("Failed creating set")
            db.session.rollback()
            flash(f"Error creating set: {e}", "danger")
            return redirect(request.url)

    return render_template('admin/create_exam_set.html', exam=exam, form=form)


# 3. Edit an existing exam set
@admin_bp.route('/exam/<int:exam_id>/sets/<int:set_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_exam_set(exam_id, set_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    exam_set = ExamSet.query.filter_by(id=set_id, exam_id=exam.id).first_or_404()
    form = ExamSetForm(obj=exam_set)

    if form.validate_on_submit():
        try:
            exam_set.name = form.name.data.strip()
            exam_set.access_password = form.access_password.data.strip()
            db.session.commit()
            flash("Set updated.", "success")
            return redirect(url_for('admin.exam_sets', exam_id=exam.id))
        except Exception as e:
            current_app.logger.exception("Failed updating set")
            db.session.rollback()
            flash(f"Error: {e}", "danger")
            return redirect(request.url)

    # Questions in set
    set_questions = (
        db.session.query(ExamQuestion, ExamSetQuestion)
        .join(ExamSetQuestion, ExamQuestion.id == ExamSetQuestion.question_id)
        .filter(ExamSetQuestion.set_id == exam_set.id)
        .order_by(asc(ExamSetQuestion.order))
        .all()
    )
    set_question_list = [q for q, sq in set_questions]

    # Available pool
    pool_questions = ExamQuestion.query.filter_by(exam_id=exam.id).all()
    pool_ids = {q.id for q in set_question_list}
    available_questions = [q for q in pool_questions if q.id not in pool_ids]

    return render_template(
        'admin/edit_exam_set.html',
        exam=exam,
        exam_set=exam_set,
        form=form,
        set_questions=set_question_list,
        available_questions=available_questions
    )

@admin_bp.route('/exam/<int:exam_id>/questions/create', methods=['GET', 'POST'])
@login_required
def create_exam_question(exam_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    form = ExamQuestionForm()

    if form.validate_on_submit():
        try:
            # create question row
            q = ExamQuestion(
                exam_id=exam.id,
                question_text=form.question_text.data.strip(),
                question_type=form.question_type.data,
                marks=form.marks.data,
            )
            db.session.add(q)
            db.session.flush()  # get q.id before adding options

            qtype = q.question_type

            # Helper to interpret checkbox values as boolean
            def is_checked_value(v):
                # checkbox might be 'on' or 'y' or 'true' or '1' depending on frontend
                return v is not None and str(v).lower() in ('on', 'y', 'true', '1')

            # ---------- MCQ ----------
            if qtype == "mcq":
                # find all keys like options-<idx>-text
                option_entries = []
                for key, val in request.form.items():
                    m = re.match(r'^options-(\d+)-text$', key)
                    if not m:
                        continue
                    idx = int(m.group(1))
                    text = (val or "").strip()
                    if not text:
                        # skip empty option texts
                        continue
                    # read corresponding is_correct checkbox if present
                    is_correct_raw = request.form.get(f'options-{idx}-is_correct')
                    is_correct = is_checked_value(is_correct_raw)
                    option_entries.append((idx, text, bool(is_correct)))

                # If no options found from dynamic inputs, try WTForms fieldlist (fallback)
                if not option_entries and getattr(form, 'options', None):
                    # form.options is a FieldList of subforms (may be preset in some cases)
                    for sub in form.options.entries:
                        text = (getattr(sub.form, 'text').data or "").strip()
                        if not text:
                            continue
                        is_correct = bool(getattr(sub.form, 'is_correct').data)
                        # index unknown here; we append with incremental index
                        option_entries.append((len(option_entries), text, is_correct))

                # sort entries by numeric index to preserve order
                option_entries.sort(key=lambda t: t[0])

                if len(option_entries) < 2:
                    # optional: enforce at least 2 options
                    current_app.logger.warning("MCQ created with fewer than 2 options")
                    # continue anyway, or raise/flash depending on your policy
                # Persist options
                for _, text, is_corr in option_entries:
                    opt = ExamOption(question_id=q.id, text=text, is_correct=bool(is_corr))
                    db.session.add(opt)

            # ---------- TRUE / FALSE ----------
            elif qtype == "true_false":
                # Prefer explicit options posted by JS: options-tf-0-text etc
                if any(k.startswith('options-tf-') for k in request.form.keys()):
                    # collect options-tf-<n>-text and their is_correct flags
                    tf_options = []
                    for key, val in request.form.items():
                        m = re.match(r'^options-tf-(\d+)-text$', key)
                        if not m:
                            continue
                        idx = int(m.group(1))
                        text = (val or "").strip()
                        if not text:
                            continue
                        is_correct = is_checked_value(request.form.get(f'options-tf-{idx}-is_correct'))
                        tf_options.append((idx, text, is_correct))
                    tf_options.sort(key=lambda t: t[0])
                    for _, text, is_corr in tf_options:
                        db.session.add(ExamOption(question_id=q.id, text=text, is_correct=bool(is_corr)))
                else:
                    # fallback: use radio tf_correct (value 'true' or 'false')
                    choice = request.form.get('tf_correct', 'true')
                    db.session.add(ExamOption(question_id=q.id, text='True', is_correct=(choice == 'true')))
                    db.session.add(ExamOption(question_id=q.id, text='False', is_correct=(choice == 'false')))

            # ---------- MATH (numeric answers) ----------
            elif qtype == "math":
                # collect math_answer-<idx> inputs
                math_answers = []
                for key, val in request.form.items():
                    m = re.match(r'^math_answer-(\d+)$', key)
                    if not m:
                        continue
                    idx = int(m.group(1))
                    raw = (val or "").strip()
                    if raw == '':
                        continue
                    # store as option text — mark as correct (we treat numeric answers as correct values)
                    math_answers.append((idx, raw))
                math_answers.sort(key=lambda t: t[0])
                for _, ans in math_answers:
                    db.session.add(ExamOption(question_id=q.id, text=ans, is_correct=True))

            # ---------- SUBJECTIVE ----------
            elif qtype == "subjective":
                # optional rubric/expected answer posted as 'subjective_rubric'
                rubric = (request.form.get('subjective_rubric') or "").strip()
                if rubric:
                    # store rubric as a non-correct option (so graders can see)
                    db.session.add(ExamOption(question_id=q.id, text=rubric, is_correct=False))
                # no student-selectable options to create

            # commit everything
            db.session.commit()
            flash("Question created.", "success")
            return redirect(url_for('admin.exam_sets', exam_id=exam.id))

        except Exception as e:
            current_app.logger.exception("Failed creating question")
            db.session.rollback()
            flash(f"Error creating question: {e}", "danger")
            return redirect(request.url)

    # GET or form not valid: render template (the template you already have)
    return render_template('admin/create_exam_question.html', exam=exam, form=form)

@admin_bp.route('/exams/add', methods=['GET', 'POST'])
@login_required
def add_exam():
    admin_only()
    form = ExamForm()

    # Populate class choices
    form.assigned_class.choices = get_class_choices()

    # Populate course choices for the selected class (default to first class if GET)
    selected_class = form.assigned_class.data or (form.assigned_class.choices[0][0] if form.assigned_class.choices else None)
    if selected_class:
        courses = Course.query.filter_by(assigned_class=selected_class).all()
        form.course_id.choices = [(c.id, c.name) for c in courses]
    else:
        form.course_id.choices = []

    if form.validate_on_submit():
        exam = Exam(
            title=form.title.data.strip(),
            course_id=form.course_id.data,  # now valid choice
            assigned_class=form.assigned_class.data,
            start_datetime=form.start_datetime.data,
            end_datetime=form.end_datetime.data,
            duration_minutes=form.duration_minutes.data,
            assignment_mode=form.assignment_mode.data,
            assignment_seed=form.assignment_seed.data
        )
        db.session.add(exam)
        db.session.commit()
        flash("Exam created successfully!", "success")
        return redirect(url_for('admin.manage_exams'))

    return render_template('admin/add_exam.html', form=form)

@admin_bp.route("/edit_exam/<int:exam_id>", methods=["GET", "POST"])
@login_required
def edit_exam(exam_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    form = ExamForm(obj=exam)

    # Populate class choices from SchoolClass table
    form.assigned_class.choices = [(c.name, c.name) for c in SchoolClass.query.order_by(SchoolClass.name).all()]

    if form.validate_on_submit():
        exam.title = form.title.data.strip()
        exam.subject = form.subject.data.strip()
        exam.assigned_class = form.assigned_class.data
        exam.start_datetime = form.start_datetime.data
        exam.end_datetime = form.end_datetime.data
        exam.duration_minutes = form.duration_minutes.data
        exam.assignment_mode = form.assignment_mode.data
        exam.assignment_seed = (form.assignment_seed.data or None)
        db.session.commit()
        flash("Exam updated successfully!", "success")
        return redirect(url_for("admin.manage_exams"))

    return render_template("admin/edit_exam.html", form=form, exam=exam)

# ===============================
# Edit Exam Question
# ===============================
@admin_bp.route('/exams/<int:exam_id>/questions/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_exam_question(exam_id, question_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    question = ExamQuestion.query.get_or_404(question_id)

    form = ExamQuestionForm(obj=question)

    # Helper to interpret checkbox/posted values as boolean
    def is_checked_value(v):
        return v is not None and str(v).lower() in ('on', 'y', 'true', '1')

    if form.validate_on_submit():
        try:
            # Update basic fields
            question.question_text = form.question_text.data.strip()
            question.question_type = form.question_type.data
            question.marks = form.marks.data
            db.session.commit()  # commit the basic changes first (optional)

            # Remove existing options (we will recreate from posted form)
            ExamOption.query.filter_by(question_id=question.id).delete()
            db.session.flush()

            qtype = question.question_type

            # ---------- MCQ ----------
            if qtype == "mcq":
                option_entries = []
                for key, val in request.form.items():
                    m = re.match(r'^options-(\d+)-text$', key)
                    if not m:
                        continue
                    idx = int(m.group(1))
                    text = (val or "").strip()
                    if not text:
                        continue
                    is_correct_raw = request.form.get(f'options-{idx}-is_correct')
                    is_correct = is_checked_value(is_correct_raw)
                    option_entries.append((idx, text, bool(is_correct)))

                # fallback to FieldList in case JS didn't post - similar approach as create
                if not option_entries and getattr(form, 'options', None):
                    for sub in form.options.entries:
                        text = (getattr(sub.form, 'text').data or "").strip()
                        if not text:
                            continue
                        is_correct = bool(getattr(sub.form, 'is_correct').data)
                        option_entries.append((len(option_entries), text, is_correct))

                option_entries.sort(key=lambda t: t[0])
                for _, text, is_corr in option_entries:
                    db.session.add(ExamOption(question_id=question.id, text=text, is_correct=bool(is_corr)))

            # ---------- TRUE / FALSE ----------
            elif qtype == "true_false":
                if any(k.startswith('options-tf-') for k in request.form.keys()):
                    tf_options = []
                    for key, val in request.form.items():
                        m = re.match(r'^options-tf-(\d+)-text$', key)
                        if not m:
                            continue
                        idx = int(m.group(1))
                        text = (val or "").strip()
                        if not text:
                            continue
                        is_correct = is_checked_value(request.form.get(f'options-tf-{idx}-is_correct'))
                        tf_options.append((idx, text, is_correct))
                    tf_options.sort(key=lambda t: t[0])
                    for _, text, is_corr in tf_options:
                        db.session.add(ExamOption(question_id=question.id, text=text, is_correct=bool(is_corr)))
                else:
                    choice = request.form.get('tf_correct', 'true')
                    db.session.add(ExamOption(question_id=question.id, text='True', is_correct=(choice == 'true')))
                    db.session.add(ExamOption(question_id=question.id, text='False', is_correct=(choice == 'false')))

            # ---------- MATH (numeric answers) ----------
            elif qtype == "math":
                math_answers = []
                for key, val in request.form.items():
                    m = re.match(r'^math_answer-(\d+)$', key)
                    if not m:
                        continue
                    idx = int(m.group(1))
                    raw = (val or "").strip()
                    if raw == '':
                        continue
                    math_answers.append((idx, raw))
                math_answers.sort(key=lambda t: t[0])
                for _, ans in math_answers:
                    db.session.add(ExamOption(question_id=question.id, text=ans, is_correct=True))

            # ---------- SUBJECTIVE ----------
            elif qtype == "subjective":
                # optional rubric/expected answer posted as 'subjective_rubric'
                rubric = (request.form.get('subjective_rubric') or "").strip()
                if rubric:
                    db.session.add(ExamOption(question_id=question.id, text=rubric, is_correct=False))
                # No further action needed: question row already created

            db.session.commit()
            flash("Question updated successfully!", "success")
            return redirect(url_for('admin.exam_sets', exam_id=exam.id))

        except Exception as e:
            current_app.logger.exception("Failed updating question")
            db.session.rollback()
            flash(f"Error updating question: {e}", "danger")
            return redirect(request.url)

    # GET: prepare initial dynamic values for template JS to prefill editors
    # collect existing options for the question
    options = []
    math_answers = []
    tf_choice = None
    rubric = ""
    opts = ExamOption.query.filter_by(question_id=question.id).all()
    if question.question_type == 'mcq':
        # keep order as stored
        for o in opts:
            options.append({'text': o.text, 'is_correct': bool(o.is_correct)})
    elif question.question_type == 'true_false':
        # detect which option is correct
        for o in opts:
            if o.text.lower().startswith('true'):
                if o.is_correct:
                    tf_choice = 'true'
            if o.text.lower().startswith('false'):
                if o.is_correct:
                    tf_choice = 'false'
        # fallback if not found set to 'true'
        if tf_choice is None:
            tf_choice = 'true'
    elif question.question_type == 'math':
        # treat all options as correct numeric answers
        for o in opts:
            math_answers.append(o.text)
    elif question.question_type == 'subjective':
        # pick a rubric (we expect the rubric to be stored as an option with is_correct False)
        if opts:
            rubric = opts[0].text or ""

    return render_template(
        "admin/edit_exam_question.html",
        form=form,
        exam=exam,
        question=question,
        initial_options=options,
        initial_math=math_answers,
        tf_choice=(tf_choice or 'true'),
        rubric=rubric
    )

# ===============================
# Delete Exam Question
# ===============================
@admin_bp.route('/exams/<int:exam_id>/questions/<int:question_id>/delete', methods=['POST'])
@login_required
def delete_exam_question(exam_id, question_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    question = ExamQuestion.query.get_or_404(question_id)

    try:
        db.session.delete(question)
        db.session.commit()
        flash("Question deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting question: {str(e)}", "danger")

    return redirect(url_for('admin.exam_sets', exam_id=exam.id))

@admin_bp.route('/exams/delete/<int:exam_id>', methods=['POST', 'GET'])
@login_required
def delete_exam(exam_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)

    try:
        db.session.delete(exam)
        db.session.commit()
        flash("Exam deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to delete exam")
        flash(f"Error deleting exam: {str(e)}", "danger")

    return redirect(url_for('admin.manage_exams'))

# 4. Delete a set
@admin_bp.route('/exam/<int:exam_id>/sets/<int:set_id>/delete', methods=['POST'])
@login_required
def delete_exam_set(exam_id, set_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    exam_set = ExamSet.query.filter_by(id=set_id, exam_id=exam.id).first_or_404()
    try:
        db.session.delete(exam_set)
        db.session.commit()
        flash("Set deleted.", "success")
    except Exception as e:
        current_app.logger.exception("Failed deleting set")
        db.session.rollback()
        flash(f"Error deleting set: {e}", "danger")
    return redirect(url_for('admin.exam_sets', exam_id=exam.id))


# ---------- AJAX / API endpoints (use these from JS) ----------

# Add one or many questions to a set (POST JSON: {"question_ids":[1,2,3]})
@admin_bp.route('/exam/<int:exam_id>/sets/<int:set_id>/add_questions', methods=['POST'])
@login_required
def add_questions_to_set(exam_id, set_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    exam_set = ExamSet.query.filter_by(id=set_id, exam_id=exam.id).first_or_404()

    payload = request.get_json() or {}
    question_ids = payload.get('question_ids') or []

    if not isinstance(question_ids, list):
        return jsonify({"status": "error", "message": "question_ids must be a list"}), 400

    added = []
    skipped = []
    try:
        for qid in question_ids:
            q = ExamQuestion.query.filter_by(id=int(qid), exam_id=exam.id).first()
            if not q:
                skipped.append({"id": qid, "reason": "question not found or belongs to another exam"})
                continue

            # skip if already in set
            exists = ExamSetQuestion.query.filter_by(set_id=exam_set.id, question_id=q.id).first()
            if exists:
                skipped.append({"id": qid, "reason": "already in set"})
                continue

            # determine order: append to end
            max_order_row = db.session.query(db.func.max(ExamSetQuestion.order)).filter_by(set_id=exam_set.id).scalar()
            next_order = (max_order_row or 0) + 1

            sq = ExamSetQuestion(set_id=exam_set.id, question_id=q.id, order=next_order)
            db.session.add(sq)
            added.append(qid)

        db.session.commit()
        return jsonify({"status": "ok", "added": added, "skipped": skipped}), 200

    except Exception as e:
        current_app.logger.exception("Failed adding questions to set")
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# Remove a question from a set
@admin_bp.route('/exam/<int:exam_id>/sets/<int:set_id>/remove_question', methods=['POST'])
@login_required
def remove_question_from_set(exam_id, set_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    exam_set = ExamSet.query.filter_by(id=set_id, exam_id=exam.id).first_or_404()

    payload = request.get_json() or {}
    qid = payload.get('question_id')
    if not qid:
        return jsonify({"status": "error", "message": "question_id required"}), 400

    try:
        sq = ExamSetQuestion.query.filter_by(set_id=exam_set.id, question_id=int(qid)).first()
        if not sq:
            return jsonify({"status": "error", "message": "not found in set"}), 404

        db.session.delete(sq)
        db.session.commit()
        return jsonify({"status": "ok", "removed": qid}), 200
    except Exception as e:
        current_app.logger.exception("Failed removing question from set")
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# Reorder questions in a set (POST JSON: {"order":[qid1, qid2, qid3]})
@admin_bp.route('/exam/<int:exam_id>/sets/<int:set_id>/reorder', methods=['POST'])
@login_required
def reorder_set_questions(exam_id, set_id):
    admin_only()
    exam = Exam.query.get_or_404(exam_id)
    exam_set = ExamSet.query.filter_by(id=set_id, exam_id=exam.id).first_or_404()

    payload = request.get_json() or {}
    order_list = payload.get('order') or []
    if not isinstance(order_list, list):
        return jsonify({"status": "error", "message": "order must be a list"}), 400

    try:
        # Simple pass over list and update order value
        for idx, qid in enumerate(order_list, start=1):
            sq = ExamSetQuestion.query.filter_by(set_id=exam_set.id, question_id=int(qid)).first()
            if not sq:
                # skip silently or return error
                continue
            sq.order = idx
            db.session.add(sq)
        db.session.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        current_app.logger.exception("Failed reordering set")
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# Admin: list timetable entries
@admin_bp.route('/exam-timetable')
@login_required
def admin_exam_timetable():
    admin_only()
    entries = ExamTimetableEntry.query.order_by(ExamTimetableEntry.date, ExamTimetableEntry.start_time).all()
    return render_template('admin/exam_timetable_list.html', entries=entries)

# Admin: add entry (GET shows form, POST saves)
@admin_bp.route('/exam-timetable/add', methods=['GET','POST'])
@login_required
def add_exam_timetable_entry():
    admin_only()
    if request.method == 'POST':
        try:
            assigned_class = request.form.get('assigned_class','').strip()
            course = request.form.get('course','').strip()
            date_str = request.form.get('date','').strip()
            start_time_str = request.form.get('start_time','').strip()
            end_time_str = request.form.get('end_time','').strip()
            room = request.form.get('room','').strip()
            building = request.form.get('building','').strip()
            floor = request.form.get('floor','').strip()
            notes = request.form.get('notes','').strip()

            # parse date/time
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()

            entry = ExamTimetableEntry(
                assigned_class=assigned_class,
                course=course,
                date=date_obj,
                start_time=start_time,
                end_time=end_time,
                room=room,
                building=building,
                floor=floor,
                notes=notes
            )
            db.session.add(entry)
            db.session.commit()
            flash("Exam timetable entry added.", "success")
            return redirect(url_for('admin.admin_exam_timetable'))
        except Exception as e:
            db.session.rollback()
            flash(f"Failed to add entry: {e}", "danger")
            return redirect(request.url)

    # GET
    return render_template('admin/add_exam_timetable_entry.html')

# Admin: delete
@admin_bp.route('/exam-timetable/delete/<int:entry_id>', methods=['POST'])
@login_required
def delete_exam_timetable_entry(entry_id):
    admin_only()
    entry = ExamTimetableEntry.query.get_or_404(entry_id)
    try:
        db.session.delete(entry)
        db.session.commit()
        flash("Entry removed.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting: {e}", "danger")
    return redirect(url_for('admin.admin_exam_timetable'))

# Manage Calendar Page
@admin_bp.route('/manage-events', methods=['GET', 'POST'])
@login_required
def manage_events():
    admin_only()

    break_types = {
        'Holiday': 'Public Holiday',
        'Vacation': 'Vacation Break',
        'Exam': 'Examination Period',
        'Midterm': 'Midterm Break',
        'Other': 'Other Activity'
    }

    def parse_date_field(val, field_name=None):
        """Return a datetime.date or None. If invalid, return None."""
        if not val:
            return None
        try:
            return datetime.strptime(val, '%Y-%m-%d').date()
        except ValueError:
            if field_name:
                flash(f"Invalid date format for {field_name}. Please use YYYY-MM-DD.", "danger")
            return None

    # Load or initialize academic year
    year = AcademicYear.query.first()

    if request.method == 'POST':
        if not year:
            year = AcademicYear()
            db.session.add(year)

        # Parse all incoming form fields into date objects (or None)
        sd = parse_date_field(request.form.get('start_date'), 'Academic Year Start')
        ed = parse_date_field(request.form.get('end_date'), 'Academic Year End')
        s1s = parse_date_field(request.form.get('semester_1_start'), 'Semester 1 Start')
        s1e = parse_date_field(request.form.get('semester_1_end'), 'Semester 1 End')
        s2s = parse_date_field(request.form.get('semester_2_start'), 'Semester 2 Start')
        s2e = parse_date_field(request.form.get('semester_2_end'), 'Semester 2 End')

        # Basic server-side validation: required fields must be provided and valid
        required_ok = all([sd, ed, s1s, s1e, s2s, s2e])
        if not required_ok:
            flash("Please provide valid dates for all academic year fields.", "danger")
            # Don't commit; re-render form with current year (possibly None)
            # NOTE: we intentionally fall through to render_template below so the user can fix input
        else:
            # Assign Python date objects to model fields (SQLAlchemy Date expects date objects)
            year.start_date = sd
            year.end_date = ed
            year.semester_1_start = s1s
            year.semester_1_end = s1e
            year.semester_2_start = s2s
            year.semester_2_end = s2e

            try:
                db.session.commit()
                flash("Academic Year settings saved.", "success")
                return redirect(url_for('admin.manage_events'))
            except Exception as exc:
                db.session.rollback()
                # Log exc if you have logging available; here we notify user
                flash("Error saving academic year. Please check server logs.", "danger")

    # Load calendar events
    calendar_events = AcademicCalendar.query.order_by(AcademicCalendar.date).all()
    cal_events = [{
        'id': e.id,
        'title': e.label,
        'start': e.date.isoformat(),
        'backgroundColor': '#28a745' if e.is_workday else '#dc3545',
        'break_type': e.break_type
    } for e in calendar_events]

    # Add semester background ranges only if dates exist
    if year and year.semester_1_start and year.semester_1_end:
        cal_events.append({
            'start': year.semester_1_start.isoformat(),
            'end': (year.semester_1_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#d1e7dd',
            'title': 'Semester 1'
        })
    if year and year.semester_2_start and year.semester_2_end:
        cal_events.append({
            'start': year.semester_2_start.isoformat(),
            'end': (year.semester_2_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#f8d7da',
            'title': 'Semester 2'
        })

    return render_template('admin/manage_events.html',
                           cal_events=cal_events,
                           break_types=break_types,
                           academic_year=year)

# Add new event
@admin_bp.route('/events/add', methods=['POST'])
@login_required
def add_event():
    admin_only()
    date = request.form.get('date')
    label = request.form.get('label')
    break_type = request.form.get('break_type')
    is_workday = bool(request.form.get('is_workday'))
    if not date or not label or not break_type:
        return "Missing fields", 400

    calendar = AcademicCalendar(
        date=datetime.strptime(date, '%Y-%m-%d').date(),
        label=label,
        break_type=break_type,
        is_workday=is_workday
    )
    db.session.add(calendar)
    db.session.commit()
    return '', 204

@admin_bp.route('/events/edit/<int:event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    admin_only()
    event = AcademicCalendar.query.get_or_404(event_id)
    event.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
    event.label = request.form.get('label')
    event.break_type = request.form.get('break_type')
    event.is_workday = bool(request.form.get('is_workday'))
    db.session.commit()
    return '', 204

@admin_bp.route('/events/delete/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    admin_only()
    event = AcademicCalendar.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return '', 204


# API endpoint for calendar drag/drop or click
@admin_bp.route('/manage-events/json')
@login_required
def events_json():
    admin_only()
    events = AcademicCalendar.query.all()
    return jsonify([
      {'id': e.id,
       'title': e.label,
       'start': e.date.isoformat(),
       'color': e.is_workday and '#28a745' or '#dc3545'
      } for e in events
    ])

# API endpoint for academic calendar
@admin_bp.route('/api/academic-calendar')
@login_required
def academic_calendar():
    # (only for admins or teachers)
    today = date.today()
    # fetch for this year
    days = AcademicCalendar.query.filter(
        extract('year', AcademicCalendar.date) == today.year
    ).all()
    return jsonify([
        {'date': d.date.isoformat(), 'label': d.label}
        for d in days if not d.is_workday
    ])

@admin_bp.route('/profile')
@login_required
def profile():
    return render_template('admin/profile.html', user=current_user)

#========================== Database Management ==========================
# in your route
from models import *

def serialize(obj):
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    result = {}
    for c in obj.__table__.columns:
        val = getattr(obj, c.name)
        if isinstance(val, (datetime, date, time)):
            result[c.name] = val.isoformat()
        else:
            result[c.name] = val
    return result

MODELS = {
    "Admins": Admin,
    "Users": User,
    "Students": StudentProfile,
    "Teachers": TeacherProfile,
    "Parents": ParentProfile,
    "Parent-Child Links": ParentChildLink,
    "Classes": SchoolClass,
    "Fee Structures": ClassFeeStructure,
    "Fee Transactions": StudentFeeTransaction,
    "Fee Balances": StudentFeeBalance,
    "Quizzes": Quiz,
    "Questions": Question,
    "Options": Option,
    "Quiz Submissions": StudentQuizSubmission,
    "Quiz Attempts": QuizAttempt,
    "Assignments": Assignment,
    "Course Materials": CourseMaterial,
    "Courses": Course,
    "Course Limits": CourseLimit,
    "Registrations": StudentCourseRegistration,
    "Timetable": TimetableEntry,
    "Teacher-Course Assignments": TeacherCourseAssignment,
    "Attendance": AttendanceRecord,
    "Academic Calendar": AcademicCalendar,
    "Academic Years": AcademicYear,
    "Appointments Slots": AppointmentSlot,
    "Appointments": AppointmentBooking,
    "Exams": Exam,
    "Exam Sets": ExamSet,
    "Exam Questions": ExamQuestion,
    "Exam Options": ExamOption,
    "Exam Submissions": ExamSubmission,
    "Exam Attempts": ExamAttempt,
    "Exam Answers": ExamAnswer,
    "Notices": Notification,
    "Messages": Message,
    "Message Reactions": MessageReaction,
    "Teacher Assessment Periods": TeacherAssessmentPeriod,
    "Teacher Assessment Questions": TeacherAssessmentQuestion,
    "Teacher Assessments": TeacherAssessment,
    "Teacher Assessment Answers": TeacherAssessmentAnswer,
    #"Chat Messages": Message
}

@admin_bp.route("/settings/result-template", methods=["GET", "POST"])
def result_template_settings():
    from utils.results_manager import ResultManager

    templates = ResultManager.get_available_templates()
    current = ResultManager.get_template_name()

    if request.method == "POST":
        selected = request.form.get("template")
        ResultManager.set_template_name(selected)
        flash("Result template updated successfully!", "success")
        return redirect(url_for("admin.result_template_settings"))

    return render_template("admin/result_template_settings.html",
                           templates=templates, current=current)


# View all tables and records
@admin_bp.route('/database')
@login_required
def view_database():
    data = {}
    for name, model in MODELS.items():
        records = model.query.all()
        data[name] = [serialize(row) for row in records]  # <-- generic serializer
    return render_template('admin/database.html', data=data)

# Update a record (POST JSON with fields to update)
import re
from flask import jsonify, request
from datetime import datetime, date, time

# helper to map human model names to slug form used in the front-end
def slugify_model_name(name: str) -> str:
    # lowercase, replace non-alnum with underscore, collapse underscores
    s = re.sub(r'[^a-z0-9]+', '_', name.lower())
    s = re.sub(r'_+', '_', s).strip('_')
    return s

def resolve_model_from_slug(slug: str):
    # direct match first (in case you ever pass the exact key)
    if slug in MODELS:
        return MODELS[slug]

    # try matching by slugified key names
    for pretty_name, Model in MODELS.items():
        if slugify_model_name(pretty_name) == slug:
            return Model

    return None

@admin_bp.route('/update/<model>/<record_id>', methods=['POST'])
@login_required
def update_record(model, record_id):
    # resolve model slug -> SQLAlchemy model
    Model = resolve_model_from_slug(model)
    if not Model:
        return jsonify({"error": "Unknown model", "model": model}), 400

    # allow numeric or string primary keys; try to cast to int first
    try:
        pk = int(record_id)
    except Exception:
        pk = record_id

    record = Model.query.get(pk)
    if not record:
        return jsonify({"error": "Record not found", "model": model, "id": record_id}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400

    # column name set for quick membership testing
    columns = {c.name.lower(): c for c in Model.__table__.columns}

    updated_fields = {}
    for key, value in data.items():
        key_l = key.lower()
        if key_l not in columns:
            # skip unknown columns (don't raise) — useful when payload contains unrelated keys
            continue

        col = columns[key_l]

        # conversion helpers
        def to_bool(v):
            if isinstance(v, bool): return v
            if v is None: return None
            vs = str(v).strip().lower()
            if vs in ('1','true','yes','y','on'): return True
            if vs in ('0','false','no','n','off',''): return False
            return bool(v)

        try:
            col_type = str(col.type).lower()
            if "boolean" in col_type:
                new_val = to_bool(value)
            elif "integer" in col_type:
                new_val = int(value) if (value != '' and value is not None) else None
            elif "float" in col_type or "numeric" in col_type or "decimal" in col_type:
                new_val = float(value) if (value != '' and value is not None) else None
            elif "date" in col_type or "time" in col_type:
                # accept ISO strings or simple date strings; try parsing
                if value in (None, ''):
                    new_val = None
                else:
                    try:
                        # datetime.fromisoformat handles 'YYYY-MM-DD' and full iso
                        new_val = datetime.fromisoformat(value)
                    except Exception:
                        # fallback: if only date, try date.fromisoformat
                        try:
                            new_val = date.fromisoformat(value)
                        except Exception:
                            # as last resort store raw string
                            new_val = value
            else:
                # default text / varchar
                new_val = value
        except Exception as e:
            # don't fail the whole update for one field; log and skip
            current_app.logger.warning(f"Failed to coerce field {key} -> {e}")
            continue

        try:
            setattr(record, key, new_val)
            updated_fields[key] = new_val
        except Exception as e:
            current_app.logger.warning(f"Failed to set attribute {key} on {Model}: {e}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("DB commit failed during admin update")
        return jsonify({"error": "DB commit failed", "details": str(e)}), 500

    return jsonify(serialize(record)), 200

# Delete a record
@admin_bp.route('/delete/<model>/<int:record_id>', methods=['DELETE'])
@login_required
def delete_record(model, record_id):
    if model not in MODELS:
        return f"Unknown model: {model}", 400

    Model = MODELS[model]
    record = Model.query.get(record_id)
    if not record:
        return f"Record with ID {record_id} not found.", 404

    db.session.delete(record)
    db.session.commit()
    return '', 204

#========================== Student Promotion ==========================
@admin_bp.route('/admin/promote-students')
def promote_all_students():
    backup_filename = backup_students_to_csv()

    students = StudentProfile.query.all()
    for student in students:
        score = calculate_student_score(student.user_id)
        promote_student(student, score)

    db.session.commit()

    # Store filename in session to display download link
    session['last_backup_file'] = backup_filename
    flash(f"All students processed for promotion. Backup saved as {backup_filename}", "success")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/download-backup/<filename>')
def download_backup(filename):
    return send_from_directory(directory='backups', path=filename, as_attachment=True)

#--------------- Assignment Management ---------------
@admin_bp.route('/manage-assignments')
@login_required
def manage_assignments():
    if not is_admin_or_teacher():
        abort(403)

    assignments = Assignment.query.order_by(Assignment.due_date.asc()).all()
    return render_template(
        f'{current_user.role}/manage_assignments.html',
        assignments=assignments,
        now=datetime.utcnow()   # ✅ datetime comparison works now
    )

@admin_bp.route('/assignments/add', methods=['GET', 'POST'])
@login_required
def add_assignment():
    if not is_admin_or_teacher():
        abort(403)

    form = AssignmentForm()

    if form.validate_on_submit():
        course_id = request.form.get('course_id', type=int)
        if not course_id:
            flash("Please select a valid course.", "danger")
            return redirect(request.url)

        course = Course.query.get(course_id)
        if not course:
            flash("Course not found.", "danger")
            return redirect(request.url)

        file = form.file.data
        filename, original_name = None, None
        if file:
            original_name = file.filename
            filename = secure_filename(original_name)
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        assignment = Assignment(
            title=form.title.data,
            description=form.description.data,
            instructions=form.instructions.data,
            course_id=course.id,          # ✅ REQUIRED
            course_name=course.name,
            assigned_class=form.assigned_class.data,
            due_date=form.due_date.data,
            filename=filename,
            original_name=original_name,
            max_score=form.max_score.data
        )

        db.session.add(assignment)
        db.session.commit()

        create_assignment_notification(assignment)
        flash('Assignment added successfully.', 'success')
        return redirect(url_for('admin.manage_assignments'))

    return render_template('admin/add_assignment.html', form=form)

def is_admin_or_teacher():
    return current_user.is_authenticated and current_user.role in ['admin', 'teacher']


@admin_bp.route('/assignments/edit/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def edit_assignment(assignment_id):
    if current_user.role != 'admin':
        abort(403)

    assignment = Assignment.query.get_or_404(assignment_id)

    # Ensure teacher owns this assignment via course
    profile = TeacherProfile.query.filter_by(user_id=current_user.user_id).first()
    if not profile or assignment.course not in [a.course for a in profile.assignments]:
        abort(403)

    form = AssignmentForm(obj=assignment)

    if form.validate_on_submit():
        assignment.title = form.title.data
        assignment.description = form.description.data
        assignment.instructions = form.instructions.data
        assignment.assigned_class = form.assigned_class.data
        assignment.due_date = form.due_date.data
        assignment.max_score = form.max_score.data

        # 🚫 course_id is NOT touched
        # ✅ course_name is kept in sync automatically
        assignment.course_name = assignment.course.name

        file = form.file.data
        if file:
            original_name = file.filename
            filename = secure_filename(original_name)
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            assignment.filename = filename
            assignment.original_name = original_name

        db.session.commit()
        flash('Assignment updated successfully.', 'success')
        return redirect(url_for('teacher.manage_assignments'))

    return render_template(
        'teacher/edit_assignment.html',
        form=form,
        assignment=assignment
    )

@admin_bp.route('/assignments/delete/<int:assignment_id>', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    if not is_admin_or_teacher():
        abort(403)

    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.filename:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], assignment.filename)
        if os.path.exists(path):
            os.remove(path)

    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted successfully.', 'success')
    return redirect(url_for('admin.manage_assignments'))

def send_notification(type, title, message, recipients, sender=None, related_type=None, related_id=None):
    """Create a notification and attach to recipients."""
    notif = Notification(
        type=type,
        title=title,
        message=message,
        sender_id=sender.user_id if sender else None,
        related_type=related_type,
        related_id=related_id
    )
    db.session.add(notif)
    db.session.flush()  # ensures notif.id is available

    # Create recipient links
    for user in recipients:
        db.session.add(NotificationRecipient(notification_id=notif.id, user_id=user.user_id))

    db.session.commit()
    return notif

#--------------- Course Materials Management ---------------
@admin_bp.route('/materials')
@login_required
def list_materials():
    materials = CourseMaterial.query.order_by(CourseMaterial.upload_date.desc()).all()
    return render_template('admin/manage_materials.html', materials=materials)

#--------------- Course Materials CRUD Operations ---------------
def get_class_choices():
    """
    Return the list of (value,label) tuples for all classes,
    so that forms can just call this instead of hard-coding.
    """
    return [
        ('Primary 1', 'Primary 1'),
        ('Primary 2', 'Primary 2'),
        ('Primary 3', 'Primary 3'),
        ('Primary 4', 'Primary 4'),
        ('Primary 5', 'Primary 5'),
        ('Primary 6', 'Primary 6'),
        ('JHS 1', 'JHS 1'),
        ('JHS 2', 'JHS 2'),
        ('JHS 3', 'JHS 3'),
        ('SHS 1', 'SHS 1'),
        ('SHS 2', 'SHS 2'),
        ('SHS 3', 'SHS 3'),
    ]

def get_course_choices(class_name):
    """
    Returns a list of (value, label) tuples for WTForms course dropdowns
    based on the selected class name.
    """
    from models import Course  # adjust import path if needed

    courses = Course.query.filter_by(assigned_class=class_name).all()
    return [(c.name, c.name) for c in courses]


@admin_bp.route('/materials')
@login_required
def manage_materials():
    materials = CourseMaterial.query.order_by(CourseMaterial.upload_date.desc()).all()
    return render_template('admin/manage_materials.html', materials=materials)

@admin_bp.route('/materials/add', methods=['GET', 'POST'])
@login_required
def add_material():
    form = MaterialForm()
    form.assigned_class.choices = get_class_choices()

    # If POST, reload the course list for the selected class
    if request.method == 'POST':
        selected_class = request.form.get('assigned_class')
        if selected_class:
            form.course_name.choices = get_course_choices(selected_class)
        else:
            form.course_name.choices = []
    else:
        form.course_name.choices = []

    print("Form submitted:", request.method)
    print("Form data valid?", form.validate_on_submit())
    print("Form errors:", form.errors)

    if form.validate_on_submit():
        saved_count = 0
        for file in form.files.data:
            filename = secure_filename(file.filename)
            file_ext = filename.rsplit('.', 1)[-1].lower()

            # Handle ZIP files
            if file_ext == 'zip':
                with tempfile.TemporaryDirectory() as tmpdir:
                    zip_path = os.path.join(tmpdir, filename)
                    file.save(zip_path)

                    with ZipFile(zip_path) as zip_ref:
                        zip_ref.extractall(tmpdir)

                    for root, _, files in os.walk(tmpdir):
                        for inner_file in files:
                            if inner_file.endswith((
                                '.jpg', '.jpeg', '.png', '.mp3', '.mp4', '.mov', '.avi',
                                '.doc', '.docx', '.xls', '.xlsx', '.pdf', '.ppt', '.txt'
                            )):
                                in_path = os.path.join(root, inner_file)
                                with open(in_path, 'rb') as f:
                                    data = f.read()

                                orig_name = secure_filename(inner_file)
                                unique_name = f"{uuid.uuid4().hex}_{orig_name}"
                                save_path = os.path.join(current_app.config['MATERIALS_FOLDER'], unique_name)
                                with open(save_path, 'wb') as out:
                                    out.write(data)

                                db.session.add(CourseMaterial(
                                    title=form.title.data,
                                    course_name=form.course_name.data,
                                    assigned_class=form.assigned_class.data,
                                    filename=unique_name,
                                    original_name=orig_name,
                                    file_type=orig_name.rsplit('.', 1)[-1].lower()
                                ))
                                saved_count += 1
            else:
                # Handle non-zip files
                orig_name = filename
                unique_name = f"{uuid.uuid4().hex}_{orig_name}"
                save_path = os.path.join(current_app.config['MATERIALS_FOLDER'], unique_name)
                file.save(save_path)

                db.session.add(CourseMaterial(
                    title=form.title.data,
                    course_name=form.course_name.data,
                    assigned_class=form.assigned_class.data,
                    filename=unique_name,
                    original_name=orig_name,
                    file_type=orig_name.rsplit('.', 1)[-1].lower()
                ))
                saved_count += 1

        db.session.commit()
        flash(f"{saved_count} material(s) uploaded successfully!", "success")
        return redirect(url_for("admin.manage_materials"))

    return render_template("admin/add_materials.html", form=form)

@admin_bp.route('/materials/edit/<int:material_id>', methods=['GET', 'POST'])
def edit_material(material_id):
    material = CourseMaterial.query.get_or_404(material_id)
    form = MaterialForm(obj=material)

    if form.validate_on_submit():
        form.populate_obj(material)
        db.session.commit()
        flash("Material updated successfully!", "success")
        return redirect(url_for('admin.list_materials'))

    return render_template('admin/edit_material.html', form=form, material=material)

@admin_bp.route('/materials/delete/<int:material_id>', methods=['POST'])
@login_required
def delete_material(material_id):
    material = CourseMaterial.query.get_or_404(material_id)
    path = os.path.join(current_app.config['MATERIALS_FOLDER'], material.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(material)
    db.session.commit()
    flash('Material deleted.', 'info')
    return redirect(url_for('admin.manage_materials'))

# Courses Management
@admin_bp.route('/courses', methods=['GET', 'POST'])
@login_required
def manage_courses():
    if request.method == 'POST':
        start_str = request.form.get('registration_start')
        end_str   = request.form.get('registration_end')
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%dT%H:%M")
            end_dt   = datetime.strptime(end_str,   "%Y-%m-%dT%H:%M")
            if end_dt <= start_dt:
                flash("End must be after start.", "danger")
            else:
                Course.set_registration_window(start_dt, end_dt)
                flash("Registration window updated.", "success")
        except Exception:
            flash("Invalid datetime format.", "danger")
        return redirect(url_for('admin.manage_courses'))

    # Fetch existing window
    start_dt, end_dt = Course.get_registration_window()
    courses = Course.query.order_by(Course.assigned_class, Course.semester).all()

    return render_template(
        'admin/manage_courses.html',
        courses=courses,
        registration_start=start_dt,
        registration_end=end_dt
    )

@admin_bp.route('/courses/add', methods=['GET','POST'])
@login_required
def add_course():
    form = CourseForm()
    if form.validate_on_submit():
        # include credit_hours from form
        c = Course(
            name=form.name.data,
            code=form.code.data,
            assigned_class=form.assigned_class.data,
            semester=form.semester.data,
            credit_hours=form.credit_hours.data,  # <-- set this explicitly
            academic_year=form.academic_year.data,
            is_mandatory=form.is_mandatory.data
        )
        db.session.add(c)
        db.session.commit()
        flash('Course added.', 'success')
        return redirect(url_for('admin.manage_courses'))
    return render_template('admin/add_edit_course.html', form=form)

@admin_bp.route('/courses/edit/<int:course_id>', methods=['GET','POST'])
@login_required
def edit_course(course_id):
    c = Course.query.get_or_404(course_id)
    form = CourseForm(obj=c)
    if form.validate_on_submit():
        form.populate_obj(c)
        db.session.commit()
        flash('Course updated.', 'success')
        return redirect(url_for('admin.manage_courses'))
    return render_template('admin/add_edit_course.html', form=form, course=c)

@admin_bp.route('/courses/delete/<int:course_id>', methods=['POST'])
@login_required
def delete_course(course_id):
    c = Course.query.get_or_404(course_id)
    db.session.delete(c)
    db.session.commit()
    flash('Course removed.', 'warning')
    return redirect(url_for('admin.manage_courses'))

#–– Limits CRUD ––
@admin_bp.route('/courses/limits')
@login_required
def manage_limits():
    limits = CourseLimit.query.order_by(CourseLimit.class_level, CourseLimit.semester).all()
    return render_template('admin/manage_limits.html', limits=limits)

@admin_bp.route('/courses/limits/add', methods=['GET','POST'])
@login_required
def add_limit():
    form = CourseLimitForm()
    if form.validate_on_submit():
        lim = CourseLimit(
            class_level    = form.class_level.data,
            semester       = form.semester.data,
            academic_year  = form.academic_year.data,
            mandatory_limit= form.mandatory_limit.data,
            optional_limit = form.optional_limit.data
        )
        db.session.add(lim)
        db.session.commit()
        flash('Limits set.', 'success')
        return redirect(url_for('admin.manage_limits'))
    return render_template('admin/add_edit_limit.html', form=form)

@admin_bp.route('/courses/limits/edit/<int:limit_id>', methods=['GET','POST'])
@login_required
def edit_limit(limit_id):
    lim = CourseLimit.query.get_or_404(limit_id)
    form = CourseLimitForm(obj=lim)
    if form.validate_on_submit():
        form.populate_obj(lim)
        db.session.commit()
        flash('Limits updated.', 'success')
        return redirect(url_for('admin.manage_limits'))
    return render_template('admin/add_edit_limit.html', form=form, limit=lim)

@admin_bp.route('/courses/limits/delete/<int:limit_id>', methods=['POST'])
@login_required
def delete_limit(limit_id):
    lim = CourseLimit.query.get_or_404(limit_id)
    db.session.delete(lim)
    db.session.commit()
    flash('Limits deleted.', 'warning')
    return redirect(url_for('admin.manage_limits'))

@admin_bp.route('/manage-timetable', methods=['GET', 'POST'])
@login_required
def manage_timetable():
    if current_user.role != 'admin':
        abort(403)

    classes = db.session.query(Course.assigned_class).distinct().all()
    class_list = [c[0] for c in classes]
    courses = Course.query.all()

    if request.method == 'POST':
        assigned_class = request.form.get('assigned_class')
        course_id = request.form.get('course_id')
        day = request.form.get('day')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')

        new_entry = TimetableEntry(
            assigned_class=assigned_class,
            course_id=course_id,
            day_of_week=day,
            start_time=datetime.strptime(start_time, "%H:%M").time(),
            end_time=datetime.strptime(end_time, "%H:%M").time()
        )
        db.session.add(new_entry)
        db.session.commit()
        flash("Timetable entry added successfully.", "success")
        return redirect(url_for('admin.manage_timetable'))

    timetable_entries = TimetableEntry.query.order_by(TimetableEntry.day_of_week, TimetableEntry.start_time).all()
    return render_template('admin/manage_timetable.html',
                           class_list=class_list,
                           courses=courses,
                           timetable=timetable_entries)

@admin_bp.route('/timetable/edit/<int:entry_id>', methods=['GET', 'POST'])
@login_required
def edit_timetable_entry(entry_id):
    entry = TimetableEntry.query.get_or_404(entry_id)
    courses = Course.query.filter_by(assigned_class=entry.assigned_class).all()

    if request.method == 'POST':
        try:
            entry.course_id = int(request.form['course_id'])
            entry.day_of_week = request.form['day']
            entry.start_time = datetime.strptime(request.form['start_time'], '%H:%M').time()
            entry.end_time = datetime.strptime(request.form['end_time'], '%H:%M').time()

            db.session.commit()
            flash('Timetable entry updated successfully.', 'success')
            return redirect(url_for('admin.manage_timetable'))
        except Exception as e:
            db.session.rollback()
            flash('Error updating entry: {}'.format(str(e)), 'danger')

    return render_template(
        'admin/edit_timetable.html',
        entry=entry,
        courses=courses,
        days=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    )

@admin_bp.route('/timetable/delete/<int:entry_id>', methods=['POST'])
@login_required
def delete_timetable_entry(entry_id):
    entry = TimetableEntry.query.get_or_404(entry_id)
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('Timetable entry deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting entry: {str(e)}', 'danger')
    return redirect(url_for('admin.manage_timetable'))

#--------------- Student Fees Management ---------------
from collections import defaultdict

from datetime import datetime

def create_fee_notification(fee_group, sender=None):
    """
    Create a notification for a fee assignment.

    Args:
        fee_group: ClassFeeStructure object
        sender: User/Admin object creating the notification. Defaults to current_user.
    """
    if sender is None:
        sender = current_user

    # Determine sender_id and type
    if hasattr(sender, 'admin_id'):
        sender_id = sender.admin_id
        sender_type = 'admin'
    elif hasattr(sender, 'user_id'):
        sender_id = sender.user_id
        sender_type = 'user'
    else:
        sender_id = None
        sender_type = 'system'

    # Parse items if stored as JSON
    items = fee_group.items
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    # Build message text
    items_text = '\n'.join([f"  • {item['description']}: {item['amount']} GHS" for item in items])
    message = (
        f"A new fee has been assigned for your class {fee_group.class_level}.\n\n"
        f"Academic Year: {fee_group.academic_year}\n"
        f"Semester: {fee_group.semester}\n"
        f"Description: {fee_group.description}\n"
        f"Total Amount: {fee_group.amount} GHS\n\n"
        f"Breakdown:\n{items_text}\n\n"
        f"Please check your Fees section for details."
    )

    # Create Notification object
    notification = Notification(
        type='fee',
        title=f'New Fee Assigned: {fee_group.description}',
        message=message,
        sender_id=sender_id,
        sender_type=sender_type,
        related_type='fee',
        related_id=fee_group.id,
        created_at=datetime.utcnow()
    )
    db.session.add(notification)
    db.session.flush()  # Get notification.id

    # Map class_level string to SchoolClass
    school_class = SchoolClass.query.filter_by(name=fee_group.class_level).first()
    if not school_class:
        db.session.rollback()
        raise ValueError(f"No class found matching '{fee_group.class_level}'")

    # Get all students in the class
    students = User.query.filter_by(class_id=school_class.id, role='student').all()

    # Create recipients for students and optionally parents
    for student in students:
        # Notify student
        db.session.add(NotificationRecipient(
            notification_id=notification.id,
            user_id=student.user_id,
            is_read=False
        ))

        # Notify parents if you have a relationship student.parents
        if hasattr(student, 'parents'):
            for parent in student.parents:
                db.session.add(NotificationRecipient(
                    notification_id=notification.id,
                    user_id=parent.user_id,
                    is_read=False
                ))

    db.session.commit()

@admin_bp.route('/assign-fees', methods=['GET', 'POST'])
@login_required
def assign_fees():
    if not current_user.is_admin:
        flash("Unauthorized", "danger")
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        class_level = request.form.get('class_level')
        academic_year = request.form.get('academic_year')
        semester = request.form.get('semester')
        group_title = request.form.get('group_title') or 'Default'

        descriptions = request.form.getlist('description[]')
        amounts = request.form.getlist('amount[]')

        # Build items list
        items = []
        total = 0.0
        for desc, amt in zip(descriptions, amounts):
            amt_f = float(amt or 0)
            items.append({'description': desc.strip(), 'amount': round(amt_f, 2)})
            total += amt_f

        # Ensure required fields
        if not class_level or not academic_year or not semester or not items:
            flash("Missing required fields.", "danger")
            return redirect(url_for('admin.assign_fees'))

        # Check if group already exists
        existing = ClassFeeStructure.query.filter_by(
            class_level=class_level,
            academic_year=academic_year,
            semester=semester,
            description=group_title
        ).first()

        if existing:
            flash(f"A fee group '{group_title}' already exists for {class_level} {academic_year} {semester}. Use edit to change it.", "warning")
            return redirect(url_for('admin.assign_fees'))

        # Create fee structure group
        new_group = ClassFeeStructure(
            class_level=class_level,
            academic_year=academic_year,
            semester=semester,
            description=group_title,
            amount=round(total, 2),
        )
        
        # Store items as JSON
        if isinstance(new_group.items, str) or new_group.items is None:
            new_group.items = json.dumps(items)
        else:
            new_group.items = items

        db.session.add(new_group)
        db.session.commit()

        # Create notification (passes current_user automatically)
        try:
            create_fee_notification(new_group, sender=current_user)
            flash("Fees assigned successfully, students notified.", "success")
        except Exception as e:
            flash(f"Fees assigned but notification failed: {str(e)}", "warning")
            print(f"Notification error: {e}")

        return redirect(url_for('admin.assign_fees'))

    # GET: fetch groups
    groups = ClassFeeStructure.query.order_by(
        ClassFeeStructure.class_level,
        ClassFeeStructure.academic_year,
        ClassFeeStructure.semester,
        ClassFeeStructure.created_at.desc()
    ).all()

    return render_template('admin/assign_fees.html', groups=groups)
    
@admin_bp.route('/edit-fee/<int:fee_id>', methods=['GET', 'POST'])
@login_required
def edit_fee(fee_id):
    group = ClassFeeStructure.query.get_or_404(fee_id)

    if request.method == 'POST':
        group.class_level = request.form['class_level']
        group.academic_year = request.form['academic_year']
        group.semester = request.form['semester']
        group.description = request.form.get('group_title', group.description)

        # get lists and rebuild items list
        descriptions = request.form.getlist('description[]')
        amounts = request.form.getlist('amount[]')
        items = []
        total = 0.0
        for d, a in zip(descriptions, amounts):
            a_f = float(a or 0)
            items.append({'description': d.strip(), 'amount': round(a_f, 2)})
            total += a_f

        group.amount = round(total, 2)
        if isinstance(group.items, str):
            group.items = json.dumps(items)
        else:
            group.items = items

        db.session.commit()
        flash("Fee group updated successfully.", "success")
        return redirect(url_for('admin.assign_fees'))

    # render edit form: pre-fill rows from group.items_list
    return render_template('admin/edit_fee.html', group=group)

@admin_bp.route('/delete-fee/<int:fee_id>', methods=['POST'])
@login_required
def delete_fee(fee_id):
    group = ClassFeeStructure.query.get_or_404(fee_id)
    db.session.delete(group)
    db.session.commit()
    flash("Fee group deleted successfully.", "success")
    return redirect(url_for('admin.assign_fees'))

@admin_bp.route('/mark_fee_paid/<int:fee_id>', methods=['POST'])
@login_required
def mark_fee_paid(fee_id):
    fee = StudentFeeBalance.query.get_or_404(fee_id)

    if fee.is_paid: 
        flash("This fee is already marked as paid.", "info")
    else:
        fee.is_paid = True
        fee.paid_on = datetime.utcnow()
        db.session.commit()
        flash("Fee marked as paid successfully.", "success")

    return redirect(url_for('admin.assign_fees'))

@admin_bp.route('/review-payments')
@login_required
def review_payments():
    if not current_user.role == 'admin':
        abort(403)
    transactions = StudentFeeTransaction.query.order_by(StudentFeeTransaction.timestamp.desc()).all()
    return render_template('admin/review_payments.html', transactions=transactions)

@admin_bp.route('/approve-payment/<int:txn_id>', methods=['POST'])
@login_required
def approve_payment(txn_id):
    txn = StudentFeeTransaction.query.get_or_404(txn_id)
    if txn.is_approved:
        flash("Already approved", "warning")
        return redirect(url_for('admin.review_payments'))

    txn.is_approved = True
    txn.reviewed_by_admin_id = current_user.id

    # ✅ Update student balance
    balance = StudentFeeBalance.query.filter_by(
        student_id=txn.student_id,
        academic_year=txn.academic_year,
        semester=txn.semester
    ).first()

    if not balance:
        balance = StudentFeeBalance(
            student_id=txn.student_id,
            academic_year=txn.academic_year,
            semester=txn.semester,
            balance=0
        )
        db.session.add(balance)

    balance.balance += txn.amount

    # ✅ Generate Receipt
    student = txn.student  # assuming relationship is set
    receipt_filename = generate_receipt(txn, student)
    receipt_path = os.path.join(current_app.config['RECEIPT_FOLDER'], receipt_filename)

    # ✅ Store filename or just ensure it exists
    # txn.receipt_filename = receipt_filename  # if you want to store it in DB

    db.session.commit()

    flash("Payment approved, balance updated, and receipt generated.", "success")
    return redirect(url_for('admin.review_payments'))


def expire_old_requests():
    now = datetime.utcnow()
    expired_requests = PasswordResetRequest.query.join(PasswordResetToken).filter(
        PasswordResetRequest.status.in_(['pending', 'emailed']),
        PasswordResetToken.expires_at < now
    ).all()

    for req in expired_requests:
        req.status = 'expired'
    if expired_requests:
        db.session.commit()


@admin_bp.route('/password-reset-requests')
@login_required
def password_reset_requests_view():
    # Expire old requests
    now = datetime.utcnow()
    expired_requests = PasswordResetRequest.query.join(PasswordResetToken).filter(
        PasswordResetRequest.status.in_(['emailed', 'email_failed']),
        PasswordResetToken.expires_at < now
    ).all()
    for req in expired_requests:
        req.status = 'expired'
    if expired_requests:
        db.session.commit()

    requests = PasswordResetRequest.query.order_by(PasswordResetRequest.requested_at.desc()).all()
    return render_template('admin/password_reset_requests.html', requests=requests)

def retry_failed_emails():
    failed_requests = PasswordResetRequest.query.filter_by(status='email_failed').all()
    for req in failed_requests:
        token = req.tokens[-1].token_hash  # last token
        try:
            send_password_reset_email(req.user, token)
            req.status = 'emailed'
            req.email_sent_at = datetime.utcnow()
        except Exception:
            continue
    db.session.commit()

@admin_bp.route('/password-reset/<int:request_id>', methods=['POST'])
@login_required
def reset_user_password(request_id):
    req = PasswordResetRequest.query.get_or_404(request_id)
    user = User.query.filter_by(user_id=req.user_id).first()
    if not user:
        flash('User not found.', 'danger')
        req.status = 'failed'
        db.session.commit()
        return redirect(url_for('admin.password_reset_requests_view'))

    temp_password = secrets.token_urlsafe(8)
    user.set_password(temp_password)
    db.session.commit()

    req.status = 'completed'
    req.completed_at = datetime.utcnow()
    db.session.commit()

    try:
        send_temporary_password_email(user, temp_password)
        flash(f'Password for {user.user_id} has been reset and emailed.', 'success')
    except Exception as e:
        current_app.logger.exception(f"Failed to send email: {e}")
        flash(f'Password reset succeeded, but email failed for {user.user_id}.', 'warning')

    return redirect(url_for('admin.password_reset_requests_view'))

@admin_bp.route('/teacher-assessment')
@login_required
def teacher_assessment_admin_home():
    if not current_user.is_admin:
        abort(403)

    active_period = TeacherAssessmentPeriod.query.filter_by(is_active=True).first()

    return render_template(
        'admin/teacher_assessment_home.html',
        active_period=active_period
    )

@admin_bp.route('/teacher-assessment/questions')
@login_required
def teacher_assessment_questions():
    if not current_user.is_admin:
        abort(403)

    questions = TeacherAssessmentQuestion.query.order_by(
        TeacherAssessmentQuestion.category,
        TeacherAssessmentQuestion.id
    ).all()

    return render_template(
        'admin/teacher_assessment_questions.html',
        questions=questions
    )

@admin_bp.route('/teacher-assessment/questions/add', methods=['GET', 'POST'])
@login_required
def add_teacher_assessment_question():
    if not current_user.is_admin:
        abort(403)

    if request.method == 'POST':
        question = request.form.get('question')
        category = request.form.get('category')

        if not question or not category:
            flash("All fields are required.", "danger")
            return redirect(request.url)

        q = TeacherAssessmentQuestion(
            question=question,
            category=category
        )
        db.session.add(q)
        db.session.commit()

        flash("Question added successfully.", "success")
        return redirect(url_for('admin.teacher_assessment_questions'))

    return render_template('admin/teacher_assessment_question_form.html')

@admin_bp.route('/teacher-assessment/questions/<int:qid>/edit', methods=['GET', 'POST'])
@login_required
def edit_teacher_assessment_question(qid):
    if not current_user.is_admin:
        abort(403)

    q = TeacherAssessmentQuestion.query.get_or_404(qid)

    if request.method == 'POST':
        q.question = request.form.get('question')
        q.category = request.form.get('category')
        q.is_active = bool(request.form.get('is_active'))

        db.session.commit()
        flash("Question updated.", "success")
        return redirect(url_for('admin.teacher_assessment_questions'))

    return render_template(
        'admin/teacher_assessment/question_form.html',
        q=q
    )

@admin_bp.route('/teacher-assessment/questions/<int:qid>/delete', methods=['POST'])
@login_required
def delete_teacher_assessment_question(qid):
    if not current_user.is_admin:
        abort(403)

    q = TeacherAssessmentQuestion.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()

    flash("Question deleted.", "success")
    return redirect(url_for('admin.teacher_assessment_questions'))

@admin_bp.route('/teacher-assessment/periods')
@login_required
def assessment_periods():
    if not current_user.is_admin:
        abort(403)

    periods = TeacherAssessmentPeriod.query.order_by(
        TeacherAssessmentPeriod.created_at.desc()
    ).all()

    return render_template(
        'admin/teacher_assessment_periods.html',
        periods=periods
    )

@admin_bp.route('/teacher-assessment/periods/add', methods=['GET', 'POST'])
@login_required
def add_assessment_period():
    if not current_user.is_admin:
        abort(403)

    if request.method == 'POST':
        academic_year = request.form.get('academic_year')
        semester = request.form.get('semester')
        start_date = datetime.strptime(request.form.get('start_date'), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.form.get('end_date'), "%Y-%m-%d").date()
        activate = request.form.get('activate')

        if not all([academic_year, semester, start_date, end_date]):
            flash("All fields are required.", "danger")
            return redirect(request.url)

        if activate:
            # Deactivate all other periods
            TeacherAssessmentPeriod.query.update({TeacherAssessmentPeriod.is_active: False})

        period = TeacherAssessmentPeriod(
            academic_year=academic_year,
            semester=semester,
            start_date=start_date,
            end_date=end_date,
            is_active=bool(activate)
        )

        db.session.add(period)
        db.session.commit()

        flash("Assessment period created successfully.", "success")
        return redirect(url_for('admin.assessment_periods'))

    return render_template('admin/teacher_assessment_period_form.html')

@admin_bp.route('/teacher-assessment/periods/<int:pid>/toggle', methods=['POST'])
@login_required
def toggle_assessment_period(pid):
    if not current_user.is_admin:
        abort(403)

    period = TeacherAssessmentPeriod.query.get_or_404(pid)

    if not period.is_active:
        # Ensure only one active period
        TeacherAssessmentPeriod.query.update({TeacherAssessmentPeriod.is_active: False})
        period.is_active = True
        flash("Assessment period activated.", "success")
    else:
        period.is_active = False
        flash("Assessment period closed.", "warning")

    db.session.commit()
    return redirect(url_for('admin.assessment_periods'))



# =====================================================
# Admin - Manage Admissions
# =====================================================
@admin_bp.route('/admissions')
@login_required
def manage_admissions():
    status = request.args.get('status')

    query = Application.query
    if status:
        query = query.filter_by(status=status)

    applications = query.order_by(Application.submitted_at.desc()).all()

    stats = {
        'total': Application.query.count(),
        'submitted': Application.query.filter_by(status='submitted').count(),
        'approved': Application.query.filter_by(status='approved').count(),
        'rejected': Application.query.filter_by(status='rejected').count()
    }

    return render_template(
        'admin/manage_admissions.html',
        applications=applications,
        status=status,
        stats=stats
    )

@admin_bp.route('/admissions/<int:app_id>')
@login_required
def view_application(app_id):
    application = Application.query.get_or_404(app_id)

    return render_template(
        'admin/view_application.html',
        application=application,
        documents=application.documents,
        results=application.exam_results
    )


@admin_bp.route('/admissions/<int:app_id>/update-status/<string:new_status>', methods=['POST'])
@login_required
def update_application_status(app_id, new_status):
    application = Application.query.get_or_404(app_id)
    
    if new_status not in ['draft', 'submitted', 'approved', 'rejected']:
        flash('Invalid status.', 'danger')
        return redirect(url_for('admin.manage_admissions'))

    # Update status
    application.status = new_status
    db.session.commit()
    flash(f'Application status updated to {new_status}.', 'success')

    # Auto-register student and send credentials if approved
    if new_status == 'approved':
        # Prefer application.applicant if you use separate Applicant model
        applicant_email = application.email or (application.applicant.email if getattr(application, 'applicant', None) else None)
        existing_user = User.query.filter_by(email=applicant_email).first() if applicant_email else None

        if not existing_user:
            # Generate unique username
            username = generate_unique_username(
                application.other_names or '',
                '',  # middle name if you have it
                application.surname or '',
                'student'
            )

            # Generate unique student ID
            prefix = 'STD'
            base_count = User.query.filter_by(role='student').count() + 1
            count = base_count
            while True:
                student_id = f"{prefix}{count:03d}"
                if not User.query.filter_by(user_id=student_id).first():
                    break
                count += 1

            # Generate temporary password
            temp_password = uuid.uuid4().hex[:8]

            new_user = User(
                user_id=student_id,
                username=username,
                email=applicant_email,
                first_name=application.other_names,
                last_name=application.surname,
                role='student',
                profile_picture='default_avatar.png'
            )
            new_user.set_password(temp_password)
            db.session.add(new_user)

            student_profile = StudentProfile(
                user_id=student_id,
                dob=application.dob,
                gender=application.gender,
                nationality=application.nationality,
                address=application.postal_address,
                phone=application.phone,
                email=applicant_email,
                guardian_name=application.guardian_name,
                guardian_relation=application.guardian_relation,
                guardian_contact=application.guardian_phone,
                current_class=application.first_choice,
                academic_year=datetime.utcnow().year
            )
            db.session.add(student_profile)

            try:
                db.session.commit()
                flash(f"Student account created! Username: {username}", "success")

                # Send credentials to applicant
                sent = send_approval_credentials_email(application, username, student_id, temp_password)
                if sent:
                    flash("Credentials email sent to the applicant.", "info")
                else:
                    flash("Student created but failed to send credentials email. Check mail logs.", "warning")

            except Exception as e:
                db.session.rollback()
                logging.exception("Failed creating student account")
                flash(f"Error creating student account: {e}", "danger")
        else:
            # Optionally, re-send credentials if admin requests
            flash("Student account already exists for this applicant.", "info")

    return redirect(url_for('admin.manage_admissions'))

@admin_bp.route('/vouchers', methods=['GET', 'POST'])
def manage_vouchers():
    if request.method == 'POST':
        try:
            count = int(request.form.get('count', 1))
        except ValueError:
            count = 1

        amount_raw = request.form.get('amount', None)
        if amount_raw:
            try:
                amount = float(amount_raw)
            except ValueError:
                amount = float(current_app.config.get('VOUCHER_DEFAULT_AMOUNT', 50.0))
        else:
            amount = float(current_app.config.get('VOUCHER_DEFAULT_AMOUNT', 50.0))

        vouchers = []
        for _ in range(max(1, count)):
            pin = f"{random.randint(100000, 999999)}"
            serial = f"{random.randint(10000000, 99999999)}"
            v = AdmissionVoucher(pin=pin, serial=serial, amount=amount)
            db.session.add(v)
            vouchers.append(v)

        db.session.commit()
        flash(f'Generated {len(vouchers)} voucher(s).', 'success')
        return redirect(url_for('admin.manage_vouchers'))

    # Fetch all vouchers with related applicant info
    vouchers = AdmissionVoucher.query.order_by(AdmissionVoucher.created_at.desc()).all()
    return render_template('admin/vouchers.html', vouchers=vouchers)

@admin_bp.route('/vouchers/create', methods=['GET', 'POST'])
def create_voucher():
    if request.method == 'POST':
        # handle form submission here
        pass
    return render_template('admin/create_voucher.html')
