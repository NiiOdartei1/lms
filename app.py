"""
LMS Flask Application

Key design principle: All database queries and heavy imports happen INSIDE
the app context (within @app.before_request or route handlers), not at module
import time.
"""
import os
import logging
import sys
from datetime import datetime

from flask import (
    Flask, current_app, render_template, redirect, url_for,
    flash, request, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# Extensions & security (lightweight, no DB access)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from flask_session import Session

# Your project config and extensions
from config import Config
from utils.extensions import db, mail, socketio

# =========================================================================
# SETUP LOGGING
# =========================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# =========================================================================
# CREATE AND CONFIGURE FLASK APP
# =========================================================================
logger.info("=" * 70)
logger.info("CREATING FLASK APP")
logger.info("=" * 70)

app = Flask(__name__)
app.config.from_object(Config)

# Set sensible defaults
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
for folder_path in [
    app.instance_path,
    app.config['UPLOAD_FOLDER'],
    app.config['MATERIALS_FOLDER'],
    app.config['PAYMENT_PROOF_FOLDER'],
    app.config['RECEIPT_FOLDER'],
    app.config['PROFILE_PICS_FOLDER'],
]:
    os.makedirs(folder_path, exist_ok=True)

logger.info("App instance path: %s", app.instance_path)

# =========================================================================
# INITIALIZE EXTENSIONS (lightweight, no app context issues)
# =========================================================================
logger.info("Initializing extensions...")

db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
socketio.init_app(app, async_mode="threading", manage_session=False)
sess = Session(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'select_portal'

logger.info("✓ Extensions initialized")

# =========================================================================
# CONTEXT PROCESSORS
# =========================================================================
@app.context_processor
def inject_csrf():
    """Make csrf_token() available in templates."""
    return dict(csrf_token=generate_csrf)

@app.context_processor
def inject_now():
    """Make now (current UTC time) available in templates."""
    return {'now': datetime.utcnow()}

@app.context_processor
def inject_active_assessment_period():
    """Lazily fetch active assessment period for templates."""
    def get_active_period():
        try:
            from models import TeacherAssessmentPeriod
            return TeacherAssessmentPeriod.query.filter_by(is_active=True).first()
        except Exception as e:
            logger.warning("Failed to fetch active assessment period: %s", e)
            return None
    return {'active_assessment_period': get_active_period}

# =========================================================================
# LOGIN MANAGER
# =========================================================================
@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for session management."""
    try:
        if isinstance(user_id, str) and user_id.startswith("admin:"):
            from models import Admin
            uid = user_id.split(":", 1)[1]
            return Admin.query.filter_by(public_id=uid).first()
        elif isinstance(user_id, str) and user_id.startswith("user:"):
            from models import User
            uid = user_id.split(":", 1)[1]
            return User.query.filter_by(public_id=uid).first()
    except Exception as e:
        logger.exception("Error in user_loader: %s", e)
    return None

# =========================================================================
# ERROR HANDLERS
# =========================================================================
@app.errorhandler(CSRFError)
def handle_csrf(e):
    return jsonify({
        'error': 'CSRF token missing or invalid',
        'reason': e.description
    }), 400

@app.after_request
def set_security_headers(response):
    """Set security-related HTTP headers."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Cache-Control', 'no-store')
    return response

# =========================================================================
# DATABASE INITIALIZATION (happens in app context)
# =========================================================================
def initialize_database():
    """
    Initialize the database tables and seed default data.
    This is called once during app startup inside app context.
    """
    try:
        logger.info("[DB] Creating all tables...")
        db.create_all()
        logger.info("[DB] ✓ Tables created/verified")
        
        # Create default admin
        logger.info("[DB] Checking for default admin...")
        from models import Admin
        super_admin = Admin.query.filter_by(username='SuperAdmin').first()
        if not super_admin:
            admin = Admin(username='SuperAdmin', admin_id='ADM001')
            admin.set_password('Password123')
            db.session.add(admin)
            db.session.commit()
            logger.info("[DB] ✓ SuperAdmin created")
        else:
            logger.info("[DB] ✓ SuperAdmin already exists")
        
        # Create default school classes
        logger.info("[DB] Initializing default classes...")
        from models import SchoolClass
        from utils.helpers import get_class_choices
        
        existing_classes = {c.name for c in SchoolClass.query.all()}
        new_count = 0
        for class_name, _ in get_class_choices():
            if class_name not in existing_classes:
                db.session.add(SchoolClass(name=class_name))
                new_count += 1
        
        if new_count > 0:
            db.session.commit()
            logger.info("[DB] ✓ Created %d default classes", new_count)
        else:
            logger.info("[DB] ✓ All default classes already exist")
            
    except Exception as e:
        logger.exception("[DB] Error during initialization: %s", e)
        raise

# =========================================================================
# DEFERRED BLUEPRINT AND MODEL IMPORTS
# =========================================================================
_app_initialized = False

@app.before_request
def before_request_init():
    """
    One-time initialization on first request.
    This runs inside app context so DB queries are safe.
    """
    global _app_initialized
    if _app_initialized:
        return
    
    logger.info("=" * 70)
    logger.info("FIRST REQUEST - INITIALIZING APP")
    logger.info("=" * 70)
    
    try:
        # Initialize database
        logger.info("[1/3] Initializing database...")
        initialize_database()
        
        # Import and register blueprints
        logger.info("[2/3] Importing and registering blueprints...")
        
        try:
            from admin_routes import admin_bp
            app.register_blueprint(admin_bp, url_prefix="/admin")
            logger.info("  ✓ admin_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import admin_bp: %s", e)
            raise
        
        try:
            from teacher_routes import teacher_bp
            app.register_blueprint(teacher_bp, url_prefix="/teacher")
            logger.info("  ✓ teacher_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import teacher_bp: %s", e)
            raise
        
        try:
            from student_routes import student_bp
            app.register_blueprint(student_bp, url_prefix="/student")
            logger.info("  ✓ student_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import student_bp: %s", e)
            raise
        
        try:
            from parent_routes import parent_bp
            app.register_blueprint(parent_bp, url_prefix="/parent")
            logger.info("  ✓ parent_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import parent_bp: %s", e)
            raise
        
        try:
            from utils.auth_routes import auth_bp
            app.register_blueprint(auth_bp)
            logger.info("  ✓ auth_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import auth_bp: %s", e)
            raise
        
        try:
            from exam_routes import exam_bp
            app.register_blueprint(exam_bp, url_prefix="/exam")
            logger.info("  ✓ exam_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import exam_bp: %s", e)
            raise
        
        try:
            from vclass_routes import vclass_bp
            app.register_blueprint(vclass_bp, url_prefix="/vclass")
            logger.info("  ✓ vclass_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import vclass_bp: %s", e)
            raise
        
        try:
            from chat_routes import chat_bp
            app.register_blueprint(chat_bp, url_prefix="/chat")
            logger.info("  ✓ chat_bp registered")
        except Exception as e:
            logger.exception("  ✗ Failed to import chat_bp: %s", e)
            raise
        
        # Import SocketIO handlers (non-fatal if fails)
        logger.info("[3/3] Importing SocketIO handlers...")
        try:
            import call_window
            logger.info("  ✓ call_window imported")
        except Exception as e:
            logger.warning("  ⚠ call_window import failed (non-fatal): %s", e)
        
        _app_initialized = True
        logger.info("=" * 70)
        logger.info("✓✓✓ APP INITIALIZATION COMPLETE ✓✓✓")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.exception("=" * 70)
        logger.exception("✗✗✗ FATAL ERROR DURING INITIALIZATION ✗✗✗")
        logger.exception("=" * 70)
        raise

# =========================================================================
# ROUTES
# =========================================================================
@app.route('/')
def home():
    try:
        return render_template('home.html')
    except Exception as e:
        logger.exception("Template error on home route: %s", e)
        return f"<h1>Template rendering error: {e}</h1>", 500

@app.route('/portal')
def select_portal():
    return render_template('portal_selection.html')

@app.route('/portal/<portal>')
def redirect_to_portal(portal):
    mapping = {
        'exams': 'exam.exam_login',
        'teachers': 'teacher.teacher_login',
        'students': 'student.student_login',
        'parents': 'parent.parent_login',
        'vclass': 'vclass.vclass_login'
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
    """Debug route to list all registered routes."""
    from urllib.parse import unquote
    lines = []
    for rule in app.url_map.iter_rules():
        lines.append(f"{rule.endpoint:30s} → {unquote(str(rule))}")
    return "<pre>" + "\n".join(sorted(lines)) + "</pre>"

# =========================================================================
# RUN
# =========================================================================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    logger.info("=" * 70)
    logger.info("Starting LMS app on 0.0.0.0:%d", port)
    logger.info("SESSION_TYPE=%s", app.config['SESSION_TYPE'])
    logger.info("=" * 70)
    socketio.run(app, host="0.0.0.0", port=port, debug=app.debug)
