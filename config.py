import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///lms.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Existing folders - adjust for production
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads', 'assignments')
    MATERIALS_FOLDER = os.path.join(os.getcwd(), 'uploads', 'materials')
    PAYMENT_PROOF_FOLDER = os.path.join('static', 'uploads', 'payments')
    RECEIPT_FOLDER = os.path.join('static', 'uploads', 'receipts')
    PROFILE_PICS_FOLDER = os.path.join('static', 'uploads', 'profile_pictures')

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'zip', 'jpg', 'jpeg', 'png', 'gif', 'mp3', 'mp4', 'mov', 'avi',
                          'doc', 'docx', 'xls', 'xlsx', 'pdf', 'ppt', 'txt'}

    # -----------------------
    # Zoom API Credentials
    # -----------------------
    ZOOM_ACCOUNT_ID = os.environ.get('ZOOM_ACCOUNT_ID')
    ZOOM_CLIENT_ID = os.environ.get('ZOOM_CLIENT_ID')
    ZOOM_CLIENT_SECRET = os.environ.get('ZOOM_CLIENT_SECRET')
