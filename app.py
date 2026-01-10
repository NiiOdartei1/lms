""" LMS Flask Application — Production Safe Key Principles
- Create tables first, then create admin
- No DB access at import time
- App factory pattern (Gunicorn-safe)
"""

import os
import logging
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, abort, flash, send_from_directory
from flask_login import LoginManager, login_required, logout_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_session import Session

from config import Config
from utils.extensions import db, mail, socketio

# ---------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# APPLICATION FACTORY
# ---------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ------------------------------------------------------------
    # Instance folder
    # ------------------------------------------------------------
    os.makedirs(app.instance_path, exist_ok=True)

    # ------------------------------------------------------------
    # Create all upload folders automatically
    # ------------------------------------------------------------
    folders = [
        app.config.get("UPLOAD_FOLDER"),
        app.config.get("MATERIALS_FOLDER"),
        app.config.get("PAYMENT_PROOF_FOLDER"),
        app.config.get("RECEIPT_FOLDER"),
        app.config.get("PROFILE_PICS_FOLDER"),
    ]
    for folder in folders:
        if folder:
            os.makedirs(folder, exist_ok=True)
            logger.info(f"Folder ready: {folder}")

    # ------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------
    db.init_app(app)
    mail.init_app(app)
    CSRFProtect(app)
    Session(app)
    socketio.init_app(app, async_mode="threading", manage_session=False)
    Migrate(app, db)

    login_manager = LoginManager()
    login_manager.login_view = "select_portal"
    login_manager.init_app(app)

    # ------------------------------------------------------------
    # Context processors
    # ------------------------------------------------------------
    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow()}

    # ------------------------------------------------------------
    # User loader
    # ------------------------------------------------------------
    @login_manager.user_loader
    def load_user(user_id):
        from models import Admin, User
        if user_id.startswith("admin:"):
            return Admin.query.filter_by(public_id=user_id[6:]).first()
        if user_id.startswith("user:"):
            return User.query.filter_by(public_id=user_id[5:]).first()
        return None

    # ------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------
    with app.app_context():
        from admin_routes import admin_bp
        from teacher_routes import teacher_bp
        from student_routes import student_bp
        from parent_routes import parent_bp
        from exam_routes import exam_bp
        from vclass_routes import vclass_bp
        from chat_routes import chat_bp
        from utils.auth_routes import auth_bp

        app.register_blueprint(admin_bp, url_prefix="/admin")
        app.register_blueprint(teacher_bp, url_prefix="/teacher")
        app.register_blueprint(student_bp, url_prefix="/student")
        app.register_blueprint(parent_bp, url_prefix="/parent")
        app.register_blueprint(exam_bp, url_prefix="/exam")
        app.register_blueprint(vclass_bp, url_prefix="/vclass")
        app.register_blueprint(chat_bp, url_prefix="/chat")
        app.register_blueprint(auth_bp)

        # ------------------------------------------------------------
        # CREATE TABLES FIRST (DEV / FIRST-TIME SETUP ONLY)
        # ------------------------------------------------------------
        try:
            from models import Admin
            # Only create tables if they don't exist (safe fallback)
            db.create_all()
            logger.info("All tables created (or already exist).")

            # --------------------------------------------------------
            # CREATE SUPERADMIN (PRODUCTION SAFE)
            # --------------------------------------------------------
            super_admin = Admin.query.filter_by(username="SuperAdmin").first()
            if not super_admin:
                admin = Admin(
                    username="SuperAdmin",
                    admin_id="ADM001"
                )
                admin.set_password("Password123")  # CHANGE after first login
                db.session.add(admin)
                db.session.commit()
                logger.info("SuperAdmin created successfully.")
        except Exception as e:
            logger.error(f"Error creating tables or SuperAdmin: {e}")

    # ------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------
    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/portal")
    def select_portal():
        return render_template("portal_selection.html")

    @app.route("/portal/<portal>")
    def redirect_to_portal(portal):
        mapping = {
            "exams": "exam.exam_login",
            "teachers": "teacher.teacher_login",
            "students": "student.student_login",
            "parents": "parent.parent_login",
            "vclass": "vclass.vclass_login",
        }
        key = portal.lower()
        if key not in mapping:
            abort(404)
        return redirect(url_for(mapping[key]))

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been logged out.", "info")
        return redirect(url_for("select_portal"))

    @app.route("/uploads/<path:filename>")
    @login_required
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app

# ---------------------------------------------------------------------
# Module-level app for Gunicorn
# ---------------------------------------------------------------------
app = create_app()
