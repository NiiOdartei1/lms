import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

    # Database (NO fallback)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads', 'assignments')
    MATERIALS_FOLDER = os.path.join(os.getcwd(), 'uploads', 'materials')
    PAYMENT_PROOF_FOLDER = os.path.join('static', 'uploads', 'payments')
    RECEIPT_FOLDER = os.path.join('static', 'uploads', 'receipts')
    PROFILE_PICS_FOLDER = os.path.join('static', 'uploads', 'profile_pictures')

    # Sessions
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True

    # External services
    ZOOM_ACCOUNT_ID = os.environ.get('ZOOM_ACCOUNT_ID')
    ZOOM_CLIENT_ID = os.environ.get('ZOOM_CLIENT_ID')
    ZOOM_CLIENT_SECRET = os.environ.get('ZOOM_CLIENT_SECRET')
