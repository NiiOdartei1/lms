def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ------------------------------------------------------------
    # Instance folders
    # ------------------------------------------------------------
    os.makedirs(app.instance_path, exist_ok=True)

    # ------------------------------------------------------------
    # Create all upload folders automatically
    # ------------------------------------------------------------
    folders = [
        app.config["UPLOAD_FOLDER"],
        app.config["MATERIALS_FOLDER"],
        app.config["PAYMENT_PROOF_FOLDER"],
        app.config["RECEIPT_FOLDER"],
        app.config["PROFILE_PICS_FOLDER"],
    ]
    for folder in folders:
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
        # CREATE DATABASE TABLES IF THEY DON'T EXIST
        # ------------------------------------------------------------
        try:
            db.create_all()
            logger.info("Database tables created successfully.")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

        # ------------------------------------------------------------
        # CREATE SUPERADMIN IF NONE EXISTS
        # ------------------------------------------------------------
        from models import Admin
        try:
            super_admin = Admin.query.filter_by(username="SuperAdmin").first()
            if not super_admin:
                admin = Admin(
                    username="SuperAdmin",
                    admin_id="ADM001"
                )
                admin.set_password("Password123")  # Change immediately after login
                db.session.add(admin)
                db.session.commit()
                logger.info("SuperAdmin created successfully.")
        except Exception as e:
            logger.error(f"Failed to create SuperAdmin: {e}")

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
