# app.py  — rewritten to use server-side filesystem sessions and robust CSRF handling
import os
import logging
from datetime import datetime
from flask import (
    Flask, current_app, render_template, redirect, url_for,
    flash, request, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# Extensions & security
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from flask_session import Session
from utils.extensions import db, mail, socketio

# your project imports
from config import Config
from utils.extensions import db, mail  # must exist

# -------------------------
# App factory-ish setup
# -------------------------
app = Flask(__name__)  # keep static_folder if you use it
app.config.from_object(Config)

app.config.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///lms.db')
app.config.setdefault('SESSION_TYPE', 'sqlalchemy')
app.config['SESSION_SQLALCHEMY'] = db
app.config.setdefault('SESSION_SQLALCHEMY_TABLE', 'sessions')
app.config.setdefault('SESSION_PERMANENT', False)
app.config.setdefault('SESSION_USE_SIGNER', True)
app.config.setdefault('UPLOAD_FOLDER', os.path.join(app.instance_path, 'uploads'))
app.config.setdefault('MATERIALS_FOLDER', os.path.join(app.instance_path, 'materials'))
app.config.setdefault('PAYMENT_PROOF_FOLDER', os.path.join(app.instance_path, 'payment_proofs'))
app.config.setdefault('RECEIPT_FOLDER', os.path.join(app.instance_path, 'receipts'))
app.config.setdefault('PROFILE_PICS_FOLDER', os.path.join(app.instance_path, 'profile_pics'))

# ensure instance & session dirs exist
os.makedirs(app.instance_path, exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['MATERIALS_FOLDER'], exist_ok=True)
os.makedirs(app.config['PAYMENT_PROOF_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_PICS_FOLDER'], exist_ok=True)

# initialize extensions
db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
socketio.init_app(app, manage_session=False)

# Flask-Session for server-side filesystem sessions
sess = Session(app)

# login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'select_portal'

# basic logging to console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("App instance path: %s", app.instance_path)

# expose generate_csrf to templates as callable: use in template as {{ csrf_token() }}
@app.context_processor
def inject_csrf():
    return dict(csrf_token=generate_csrf)

# inject current time
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

@app.context_processor
def inject_active_assessment_period():
    def get_active_period():
        try:
            return TeacherAssessmentPeriod.query.filter_by(is_active=True).first()
        except Exception:
            return None

    return {
        'active_assessment_period': get_active_period
    }

# -------------------------
# Import models and blueprints AFTER extensions are ready
# -------------------------
# (this avoids circular imports where models import `db` from utils.extensions)
from models import (
    PasswordResetToken, TeacherAssessmentPeriod, User, Admin, SchoolClass, StudentProfile,
    TeacherProfile, ParentProfile, Exam, Quiz, ExamSet, PasswordResetRequest
)

# blueprints
from admin_routes import admin_bp
from teacher_routes import teacher_bp
from student_routes import student_bp
from parent_routes import parent_bp
from utils.auth_routes import auth_bp
from exam_routes import exam_bp
from vclass_routes import vclass_bp
from chat_routes import chat_bp

# Register blueprints
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(teacher_bp, url_prefix="/teacher")
app.register_blueprint(student_bp, url_prefix="/student")
app.register_blueprint(parent_bp, url_prefix="/parent")
app.register_blueprint(auth_bp)  # no prefix
app.register_blueprint(exam_bp, url_prefix="/exam")
app.register_blueprint(vclass_bp, url_prefix="/vclass")
app.register_blueprint(chat_bp, url_prefix="/chat")

# -------------------------
# Login loader (adjust to your user id format)
# -------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        if isinstance(user_id, str) and user_id.startswith("admin:"):
            uid = user_id.split(":", 1)[1]
            return Admin.query.filter_by(public_id=uid).first()

        elif isinstance(user_id, str) and user_id.startswith("user:"):
            uid = user_id.split(":", 1)[1]
            return User.query.filter_by(public_id=uid).first()

    except Exception as e:
        logger.exception("user_loader error: %s", e)

    return None

# -------------------------
with app.app_context():
    import call_window
    db.create_all()

    # create default super admin
    super_admin = Admin.query.filter_by(username='SuperAdmin').first()
    if not super_admin:
        admin = Admin(username='SuperAdmin', admin_id='ADM001')
        admin.set_password('Password123')
        db.session.add(admin)
        db.session.commit()

    # create default classes
    try:
        from utils.helpers import get_class_choices
        existing = {c.name for c in SchoolClass.query.all()}
        for name, _ in get_class_choices():
            if name not in existing:
                db.session.add(SchoolClass(name=name))
        db.session.commit()
    except Exception:
        pass

# -------------------------
# Error handlers
# -------------------------
@app.errorhandler(CSRFError)
def handle_csrf(e):
    return jsonify({'error': 'CSRF token missing or invalid', 'reason': e.description}), 400

@app.after_request
def set_headers(response):
    # keep these; adjust caching policy as needed
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Do NOT aggressively cache dynamic pages — keep small default
    response.headers.setdefault('Cache-Control', 'no-store')
    return response

# -------------------------
# DB initialization — run once per server start (not on every request)
# -------------------------
@app.before_request
#def initialize_database_once():
#    try:
#        db.create_all()
#        # create a default super admin if missing
#        super_admin = Admin.query.filter_by(username='SuperAdmin').first()
#        if not super_admin:
#            admin = Admin(username='SuperAdmin', admin_id='ADM001')
#            admin.set_password('Password123')
#            db.session.add(admin)
#            db.session.commit()
#            logger.info("SuperAdmin created.")
#        # ensure default classes exist, using your helper
#        try:
#            from utils.helpers import get_class_choices
#            existing = {c.name for c in SchoolClass.query.all()}
#            for name, _ in get_class_choices():
#                if name not in existing:
#                    db.session.add(SchoolClass(name=name))
#            db.session.commit()
#        except Exception:
#            logger.exception("Failed to populate default classes (helper error)")
#    except Exception:
#        logger.exception("Error creating database/tables")

# -------------------------
# Routes (kept small — move heavy routes to blueprints)
# -------------------------
@app.route('/')
def home():
    try:
        return render_template('home.html')
    except Exception as e:
        logger.exception("Template error on / : %s", e)
        return f"<h1>Template rendering error: {e}</h1>", 500

@app.route('/portal')
def select_portal():
    return render_template('portal_selection.html')

@app.route('/portal/<portal>')
def redirect_to_portal(portal):
    mapping = {
        'exams':        'exam.exam_login',
        'teachers':     'teacher.teacher_login',
        'students':     'student.student_login',
        'parents':      'parent.parent_login',
        'vclass':       'vclass.vclass_login'
    }
    key = portal.lower()
    if key not in mapping:
        abort(404)
    return redirect(url_for(mapping[key]))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('select_portal'))

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    filename = secure_filename(filename)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

@app.route('/routes')
def list_routes():
    from urllib.parse import unquote
    lines = []
    for rule in app.url_map.iter_rules():
        lines.append(f"{rule.endpoint:30s} → {unquote(str(rule))}")
    return "<pre>" + "\n".join(sorted(lines)) + "</pre>"

# -------------------------
# Helpful debug endpoint to inspect session storage (only in debug mode)
# -------------------------
#@app.route('/_debug/session-files')
#def debug_session_files():
#    if not app.debug:
#        abort(403)
#    d = app.config['SESSION_FILE_DIR']
#    try:
#        files = os.listdir(d)
#        return jsonify({"session_dir": d, "files": files})
#    except Exception as e:
#        return jsonify({"error": str(e), "dir": d}), 500

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    # show important runtime info
    logger.info("Starting LMS app on 0.0.0.0:5000")
    logger.info("SESSION_TYPE=%s", app.config['SESSION_TYPE'])
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), debug=app.debug)
