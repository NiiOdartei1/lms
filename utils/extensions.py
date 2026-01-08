#UTILS/EXTENSIONS.PY
from flask_sqlalchemy import SQLAlchemy
from flask_mailman import Mail
from flask_socketio import SocketIO

db = SQLAlchemy()
mail = Mail()
socketio = SocketIO(cors_allowed_origins="*")  # ✅ add this line
