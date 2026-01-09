"""
Flask extensions - instantiated here but configured in app factory
"""
from flask_sqlalchemy import SQLAlchemy
from flask_mailman import Mail
from flask_socketio import SocketIO

# Create bare instances (no config yet)
db = SQLAlchemy()
mail = Mail()
socketio = SocketIO()  # Initialize WITHOUT parameters - config happens in init_app()
