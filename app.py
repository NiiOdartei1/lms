import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # Uploads
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads', 'assignments')
    MATERIALS_FOLDER = os.path.join(os.getcwd(), 'uploads', 'materials')
    PAYMENT_PROOF_FOLDER = os.path.join('static', 'uploads', 'payments')
    RECEIPT_FOLDER = os.path.join('static', 'uploads', 'receipts')
    PROFILE_PICS_FOLDER = os.path.join('static', 'uploads', 'profile_pictures')

    # Zoom
    ZOOM_ACCOUNT_ID = os.environ.get('ZOOM_ACCOUNT_ID')
    ZOOM_CLIENT_ID = os.environ.get('ZOOM_CLIENT_ID')
    ZOOM_CLIENT_SECRET = os.environ.get('ZOOM_CLIENT_SECRET')
