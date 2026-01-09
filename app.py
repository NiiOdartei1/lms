# app.py
import os
import logging
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    flash, request, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# ====== Basic imports for extensions (safe - these do not touch DB yet) ======
from flask_login import LoginManager, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from flask_session import Session
# utils/extensions should expose SQLAlchemy, Mail, SocketIO instances (no initialization side effects)
from utils.extensions import db, mail, socketio

# Config object with DATABASE_URL pointing at your MySQL (e.g. mysql+pymysql://...)
from config import Config

# ====== Logging ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Create app and load config ======
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config.from_object(Config)

# Ensure you use SQLAlchemy-backed server sessions (no filesystem session dir)
app.config.setdefault("SESSION_TYPE", "sqlalchemy")          # store sessions in DB
app.config.setdefault("SESSION_SQLALCHEMY_TABLE", "sessions")
# SESSION_SQLALCHEMY will be set to the db object below (after db.init_app)
app.config.setdefault("SESSION_PERMANENT", False)
app.config.setdefault("SESSION_USE_SIGNER", True)

# optional: upload folders (we're not creating directories on disk by default)
# If you still plan to keep uploads on disk in a production deployment,
# replace these with a cloud storage path or ensure the path is ephemeral.
app.config.setdefault('UPLOAD_FOLDER', os.environ.get('UPLOAD_FOLDER', '/tmp/uploads'))
app.config.setdefault('MATERIALS_FOLDER', os.environ.get('MATERIALS_FOLDER', '/tmp/materials'))
app.config.setdefault('PAYMENT_PROOF_FOLDER', os.environ.get('PAYMENT_PROOF_FOLDER', '/tmp/payment_proofs'))
app.config.setdefault('RECEIPT_FOLDER', os.environ.get('RECEIPT_FOLDER', '/tmp/receipts'))
app.config.setdefault('PROFILE_PICS_FOLDER', os.environ.get('PROFILE_PICS_FOLDER', '/tmp/profile_pics'))

# ====== Initialize extensions (safe; they need the app config) ======
db.init_app(app)
# give flask-session the SQLAlchemy instance
app.config['SESSION_SQLALCHEMY'] = db
sess = Session(app)               # server-side sessions (SQLAlchemy)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

# SocketIO: use threading mode to avoid eventlet/gevent requirement on Render
# manage_session=False means flask-session handles sessions (we use DB sessions)
socketio.init_app(app, async_mode="threading", manage_session=False)

# ====== Login manager (define now; loader registered below inside app_context) ======
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'select_portal'

# ====== Safe context processors ======
@app.context_processor
def inject_csrf():
    # expose callable to templates: use as {{ csrf_token() }}
    return dict(csrf_token=generate_csrf)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# Provide a lazy callable that queries DB only when template calls it inside a request.
# Template usage: {{ get_active_assessment_period() }}
@app.context_processor
def inject_active_assessment_period():
    def get_active_assessment_period():
        from models import TeacherAssessmentPeriod  # import inside request/app context
        try:
            return TeacherAssessmentPeriod.query.filter_by(is_active=True).first()
        except Exception:
            return None
    return {'get_active_assessment_period': get_active_assessment_period}

# ====== Error handlers ======
@app.errorhandler(CSRFError)
def handle_csrf(e):
    return jsonify({'error': 'CSRF token missing or invalid', 'reason': e.description}), 400

@app.after_request
def set_headers(response):
    # basic security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Cache-Control', 'no-store')
    return response

# ====== One-time, application-level initialization inside app.app_context() ======
# This MUST run at import time but inside app.app_context() to avoid "outside app context" errors.
with app.app_context():
    logger.info("=" * 60)
    logger.info("APP BOOTSTRAP: importing models, blueprints, and initializing DB")
    logger.info("=" * 60)

    # ---- Import models (only now, inside app context) ----
    # (models should import db from utils.extensions; importing here avoids import-time DB calls)
    from models import (
        PasswordResetToken, TeacherAssessmentPeriod, User, Admin, SchoolClass,
        StudentProfile, TeacherProfile, ParentProfile, Exam, Quiz, ExamSet,
        PasswordResetRequest
    )
    logger.info("Models imported.")

    # ---- Import socket handlers (call_window) ----
    # This file registers socket handlers using `socketio.on(...)`
    try:
        import call_window
        logger.info("call_window (SocketIO handlers) imported.")
    except Exception as e:
        logger.exception("call_window import failed (continue if not ready): %s", e)

    # ---- Import and register blueprints ----
    try:
        from admin_routes import admin_bp
        from teacher_routes import teacher_bp
        from student_routes import student_bp
        from parent_routes import parent_bp
        from utils.auth_routes import auth_bp
        from exam_routes import exam_bp
        from vclass_routes import vclass_bp
        from chat_routes import chat_bp

        app.register_blueprint(admin_bp, url_prefix="/admin")
        app.register_blueprint(teacher_bp, url_prefix="/teacher")
        app.register_blueprint(student_bp, url_prefix="/student")
        app.register_blueprint(parent_bp, url_prefix="/parent")
        app.register_blueprint(auth_bp)
        app.register_blueprint(exam_bp, url_prefix="/exam")
        app.register_blueprint(vclass_bp, url_prefix="/vclass")
        app.register_blueprint(chat_bp, url_prefix="/chat")

        logger.info("Blueprints registered.")
    except Exception as e:
        # log but don't crash deployment; you'll see the problem in logs
        logger.exception("Blueprint import/register failed: %s", e)
        raise

    # ---- Login loader (using models imported above) ----
    @login_manager.user_loader
    def load_user(user_id):
        try:
            if isinstance(user_id, str) and user_id.startswith("admin:"):
                uid = user_id.split(":", 1)[1]
                return Admin.query.filter_by(public_id=uid).first()
            if isinstance(user_id, str) and user_id.startswith("user:"):
                uid = user_id.split(":", 1)[1]
                return User.query.filter_by(public_id=uid).first()
        except Exception as e:
            logger.exception("user_loader error: %s", e)
        return None

    logger.info("Login loader configured.")

    # ---- Create DB tables & session table ----
    try:
        db.create_all()
        logger.info("db.create_all() executed.")
    except Exception as e:
        logger.exception("db.create_all() failed: %s", e)
        raise

    # ---- Ensure flask-session sessions table exists ----
    # For some setups, flask-session expects the sessions table; create_all above will include
    # the session table model from flask-session if the extension added it; if not, you may need
    # to create manually depending on your flask-session implementation.
    logger.info("Bootstrap complete.")

# ====== Routes (keep light; heavy logic in blueprints) ======
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
    from flask_login import logout_user as _logout
    _logout()
    flash("You have been logged out.", "info")
    return redirect(url_for('select_portal'))

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    # NOTE: If you are moving away from filesystem upload storage, update this route to proxy from cloud storage.
    filename = secure_filename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/routes')
def list_routes():
    from urllib.parse import unquote
    lines = []
    for rule in app.url_map.iter_rules():
        lines.append(f"{rule.endpoint:30s} → {unquote(str(rule))}")
    return "<pre>" + "\n".join(sorted(lines)) + "</pre>"

# ====== Small dev-only debug endpoint (disabled when not debug) ======
@app.route('/_debug/session-count')
def debug_session_count():
    if not app.debug:
        abort(403)
    # Count rows in sessions table if exists
    try:
        session_table = app.config.get('SESSION_SQLALCHEMY_TABLE', 'sessions')
        res = db.session.execute(f"SELECT COUNT(*) as cnt FROM {session_table}").first()
        return jsonify({'session_table': session_table, 'count': int(res.cnt)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ====== Run (development) ======
if __name__ == "__main__":
    logger.info("Starting development server (socketio.run)...")
    # For local/dev: use socketio.run so the websocket endpoints work
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), debug=app.debug)
