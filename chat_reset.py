# chat_reset.py
from app import app       # import your Flask app
from utils.extensions import db
from models import Conversation, ConversationParticipant, Message

with app.app_context():   # use the actual app context
    # Drop chat tables
    Message.__table__.drop(db.engine, checkfirst=True)
    ConversationParticipant.__table__.drop(db.engine, checkfirst=True)
    Conversation.__table__.drop(db.engine, checkfirst=True)

    # Recreate chat tables
    Conversation.__table__.create(db.engine)
    ConversationParticipant.__table__.create(db.engine)
    Message.__table__.create(db.engine)

    print("Chat tables reset successfully.")
