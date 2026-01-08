# app.py  — BULLETPROOF FIX: Delay ALL blueprint imports
import os
import logging
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    flash, request, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# ===== CRITICAL: Only import extensions and config =====
from flask_login import LoginManager, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from flask_session import Session
from utils.extensions import db, mail, socketio
from config import Config

# ===== Setup logging =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== Create Flask app =====
app = Flask(__name__)
app.config.from_object(Config)

# ===== Configure paths =====
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

# ===== Initialize extensions =====
db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
socketio.init_app(app, async_mode="threading", manage_session=False)
sess = Session(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'select_portal'

# ===== Context processors =====
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

# ===== Error handlers =====
@app.errorhandler(CSRFError)
def handle_csrf(e):
    return jsonify({'error': 'CSRF token missing or invalid', 'reason': e.description}), 400

@app.after_request
def set_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Cache-Control', 'no-store')
    return response

# ===== Startup flag =====
_startup_done = False

# ===== ONE-TIME initialization (must be FIRST before_request) =====
@app.before_request
def initialize_app_once():
    global _startup_done
    if _startup_done:
        return
    
    logger.info("=" * 70)
    logger.info("STARTING ONE-TIME APP INITIALIZATION")
    logger.info("=" * 70)
    
    try:
        # Step 1: Import models
        logger.info("[1/8] Importing models...")
        from models import (
            PasswordResetToken, TeacherAssessmentPeriod, User, Admin, SchoolClass,
            StudentProfile, TeacherProfile, ParentProfile, Exam, Quiz, ExamSet,
            PasswordResetRequest
        )
        logger.info("      ✓ Models imported successfully")
        
        # Step 2: Import call_window (SocketIO)
        logger.info("[2/8] Importing call_window (SocketIO handlers)...")
        import call_window
        logger.info("      ✓ call_window imported successfully")
        
        # Step 3: Import blueprints (MUST happen after models)
        logger.info("[3/8] Importing blueprints...")
        try:
            from admin_routes import admin_bp
            logger.info("      ✓ admin_bp imported")
        except Exception as e:
            logger.exception("      ✗ admin_bp failed: %s", e)
            raise
        
        try:
            from teacher_routes import teacher_bp
            logger.info("      ✓ teacher_bp imported")
        except Exception as e:
            logger.exception("      ✗ teacher_bp failed: %s", e)
            raise
        
        try:
            from student_routes import student_bp
            logger.info("      ✓ student_bp imported")
        except Exception as e:
            logger.exception("      ✗ student_bp failed: %s", e)
            raise
        
        try:
            from parent_routes import parent_bp
            logger.info("      ✓ parent_bp imported")
        except Exception as e:
            logger.exception("      ✗ parent_bp failed: %s", e)
            raise
        
        try:
            from utils.auth_routes import auth_bp
            logger.info("      ✓ auth_bp imported")
        except Exception as e:
            logger.exception("      ✗ auth_bp failed: %s", e)
            raise
        
        try:
            from exam_routes import exam_bp
            logger.info("      ✓ exam_bp imported")
        except Exception as e:
            logger.exception("      ✗ exam_bp failed: %s", e)
            raise
        
        try:
            from vclass_routes import vclass_bp
            logger.info("      ✓ vclass_bp imported")
        except Exception as e:
            logger.exception("      ✗ vclass_bp failed: %s", e)
            raise
        
        try:
            from chat_routes import chat_bp
            logger.info("      ✓ chat_bp imported")
        except Exception as e:
            logger.exception("      ✗ chat_bp failed: %s", e)
            raise
        
        # Step 4: Register blueprints
        logger.info("[4/8] Registering blueprints...")
        app.register_blueprint(admin_bp, url_prefix="/admin")
        app.register_blueprint(teacher_bp, url_prefix="/teacher")
        app.register_blueprint(student_bp, url_prefix="/student")
        app.register_blueprint(parent_bp, url_prefix="/parent")
        app.register_blueprint(auth_bp)
        app.register_blueprint(exam_bp, url_prefix="/exam")
        app.register_blueprint(vclass_bp, url_prefix="/vclass")
        app.register_blueprint(chat_bp, url_prefix="/chat")
        logger.info("      ✓ Blueprints registered successfully")
        
        # Step 5: Setup login loader
        logger.info("[5/8] Setting up login manager...")
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
        logger.info("      ✓ Login manager setup complete")
        
        # Step 6: Database initialization
        logger.info("[6/8] Initializing database...")
        db.create_all()
        logger.info("      ✓ Database tables created/verified")
        
        # Step 7: Create default admin
        logger.info("[7/8] Setting up default admin...")
        super_admin = Admin.query.filter_by(username='SuperAdmin').first()
        if not super_admin:
            admin = Admin(username='SuperAdmin', admin_id='ADM001')
            admin.set_password('Password123')
            db.session.add(admin)
            db.session.commit()
            logger.info("      ✓ SuperAdmin created")
        else:
            logger.info("      ✓ SuperAdmin already exists")
        
        # Step 8: Create default classes
        logger.info("[8/8] Setting up default classes...")
        try:
            from utils.helpers import get_class_choices
            existing = {c.name for c in SchoolClass.query.all()}
            created = 0
            for name, _ in get_class_choices():
                if name not in existing:
                    db.session.add(SchoolClass(name=name))
                    created += 1
            if created:
                db.session.commit()
                logger.info(f"      ✓ Created {created} default classes")
            else:
                logger.info("      ✓ All default classes already exist")
        except Exception as e:
            logger.exception("      ⚠ Class setup warning (non-fatal): %s", e)
        
        logger.info("=" * 70)
        logger.info("✓✓✓ APP INITIALIZATION COMPLETE - READY TO SERVE REQUESTS ✓✓✓")
        logger.info("=" * 70)
        _startup_done = True
        
    except Exception as e:
        logger.exception("=" * 70)
        logger.exception("✗✗✗ FATAL ERROR DURING INITIALIZATION ✗✗✗")
        logger.exception("=" * 70)
        raise

# ===== Routes =====
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
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/routes')
def list_routes():
    from urllib.parse import unquote
    lines = []
    for rule in app.url_map.iter_rules():
        lines.append(f"{rule.endpoint:30s} → {unquote(str(rule))}")
    return "<pre>" + "\n".join(sorted(lines)) + "</pre>"

# ===== Run =====
if __name__ == "__main__":
    logger.info("Starting LMS app on 0.0.0.0:5000")
    logger.info("SESSION_TYPE=%s", app.config['SESSION_TYPE'])
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), debug=app.debug)
    
