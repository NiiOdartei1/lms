# app.py  — Minimal startup, deferred imports to avoid context errors
import os
import logging
from datetime import datetime
from flask import (
    Flask, current_app, render_template, redirect, url_for,
    flash, request, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# Extensions & security (these don't require app context)
from flask_login import LoginManager, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from flask_session import Session

# DO NOT import db, mail, socketio yet — initialize them first
from utils.extensions import db, mail, socketio
from config import Config

# -------------------------
# Basic setup
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# Flask app creation
# -------------------------
app = Flask(__name__)
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

# Ensure directories exist
for folder in [
    app.instance_path,
    app.config['UPLOAD_FOLDER'],
    app.config['MATERIALS_FOLDER'],
    app.config['PAYMENT_PROOF_FOLDER'],
    app.config['RECEIPT_FOLDER'],
    app.config['PROFILE_PICS_FOLDER'],
]:
    os.makedirs(folder, exist_ok=True)

logger.info("App instance path: %s", app.instance_path)

# -------------------------
# Initialize extensions (BEFORE any model/blueprint imports)
# -------------------------
db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
socketio.init_app(app, async_mode="threading", manage_session=False)
sess = Session(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'select_portal'

# -------------------------
# Context processors
# -------------------------
@app.context_processor
def inject_csrf():
    return dict(csrf_token=generate_csrf)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

@app.context_processor
def inject_active_assessment_period():
    def get_active_period():
        try:
            from models import TeacherAssessmentPeriod
            return TeacherAssessmentPeriod.query.filter_by(is_active=True).first()
        except Exception:
            return None
    return {'active_assessment_period': get_active_period}

# -------------------------
# Error handlers (before imports)
# -------------------------
@app.errorhandler(CSRFError)
def handle_csrf(e):
    return jsonify({'error': 'CSRF token missing or invalid', 'reason': e.description}), 400

@app.after_request
def set_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Cache-Control', 'no-store')
    return response

# -------------------------
# Flag to track if we've done startup initialization
# -------------------------
_startup_complete = False

def _do_startup_init():
    """
    Run ALL initialization that requires app context.
    This is called once on first request, not at module load time.
    """
    global _startup_complete
    if _startup_complete:
        return
    
    try:
        # NOW import models, blueprints (they can safely use db, etc.)
        logger.info("Importing models...")
        from models import (
            PasswordResetToken, TeacherAssessmentPeriod, User, Admin, SchoolClass, 
            StudentProfile, TeacherProfile, ParentProfile, Exam, Quiz, ExamSet, 
            PasswordResetRequest
        )
        
        logger.info("Importing call_window handlers...")
        import call_window
        
        logger.info("Importing blueprints...")
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
        app.register_blueprint(auth_bp)
        app.register_blueprint(exam_bp, url_prefix="/exam")
        app.register_blueprint(vclass_bp, url_prefix="/vclass")
        app.register_blueprint(chat_bp, url_prefix="/chat")
        
        # Setup login loader (NOW that User/Admin models exist)
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
        
        # Database initialization
        logger.info("Creating database tables...")
        db.create_all()
        
        # Create default super admin
        super_admin = Admin.query.filter_by(username='SuperAdmin').first()
        if not super_admin:
            admin = Admin(username='SuperAdmin', admin_id='ADM001')
            admin.set_password('Password123')
            db.session.add(admin)
            db.session.commit()
            logger.info("SuperAdmin created.")
        
        # Create default classes
        try:
            from utils.helpers import get_class_choices
            existing = {c.name for c in SchoolClass.query.all()}
            for name, _ in get_class_choices():
                if name not in existing:
                    db.session.add(SchoolClass(name=name))
            db.session.commit()
            logger.info("Default classes initialized.")
        except Exception as e:
            logger.exception("Failed to populate default classes: %s", e)
        
        _startup_complete = True
        logger.info("Startup initialization complete!")
        
    except Exception as e:
        logger.exception("FATAL: Startup initialization failed: %s", e)
        raise

# -------------------------
# Hook to ensure startup happens before first request
# -------------------------
@app.before_request
def ensure_startup():
    _do_startup_init()

# -------------------------
# Routes
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
# Run
# -------------------------
if __name__ == "__main__":
    logger.info("Starting LMS app on 0.0.0.0:5000")
    logger.info("SESSION_TYPE=%s", app.config['SESSION_TYPE'])
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), debug=app.debug)
