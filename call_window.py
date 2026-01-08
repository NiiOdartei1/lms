# call_window.py  — Zoom-style call handling via SocketIO
from flask_socketio import emit, join_room
from flask_login import current_user
from models import Admin, Conversation, ConversationParticipant, User
from datetime import datetime
from utils.extensions import socketio
from utils.notifications import create_missed_call_notification

# Track connected users
connected_users = set()

# Helper function (reuse from chat.py if needed)

# Helper function (reuse from chat.py if needed)
# -------------------------
# Zoom-Style Call Handlers
# -------------------------
def resolve_person(pub_id):
    user = User.query.filter_by(public_id=pub_id).first()
    if user: return user, getattr(user, "role","user")
    admin = Admin.query.filter_by(public_id=pub_id).first()
    if admin: return admin, "admin"
    return None, None

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.public_id}")
        connected_users.add(current_user.public_id)
    if not current_user.is_authenticated:
        return

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        connected_users.discard(current_user.public_id)

@socketio.on('call_signal')
def call_signal(data):
    to_pub = data.get("to_public_id")
    signal_type = data.get("signal_type")
    if not to_pub: return

    # Check if target user is connected
    if to_pub not in connected_users:
        # Only create missed call notification for the initial offer, not for ICE candidates or answers
        if signal_type == 'offer':
            target_user = User.query.filter_by(public_id=to_pub).first()
            if target_user:
                caller_name = getattr(current_user, "full_name", current_user.username)
                create_missed_call_notification(caller_name, target_user.user_id, data.get("conversation_id"))
                # Notify the caller that the call failed
                emit('call_failed', {
                    "reason": "user_offline",
                    "target_name": target_user.full_name,
                    "conversation_id": data.get("conversation_id")
                }, room=f"user_{current_user.public_id}")
        return

    emit('call_signal', {
        "conversation_id": data.get("conversation_id"),
        "from_public_id": current_user.public_id,
        "from_name": getattr(current_user, "full_name", current_user.username),
        "signal_type": data.get("signal_type"),
        "signal_data": data.get("signal_data")
    }, room=f"user_{to_pub}")

@socketio.on('call_end')
def call_end(data):
    target_pub = data.get("target_public_id")
    conv_id = data.get("conversation_id")
    if not target_pub or not conv_id: return

    # Emit to target user
    emit('call_end', {
        "conversation_id": conv_id,
        "from_public_id": current_user.public_id
    }, room=f"user_{target_pub}")

    # Also emit back to sender to ensure both sides clean up
    emit('call_end', {
        "conversation_id": conv_id,
        "from_public_id": target_pub  # The target becomes the "from" for the sender
    }, room=f"user_{current_user.public_id}")

# -------------------------
# Group Calls
# -------------------------
@socketio.on('group_call_initiate')
def group_call_initiate(data):
    conv_id = data.get("conversation_id")
    conv = Conversation.query.get(conv_id)
    if not conv: return
    caller_id = current_user.public_id
    caller_name = getattr(current_user, "full_name", current_user.username)
    participants = [
        {"public_id": p.user_public_id,
         "name": getattr(resolve_person(p.user_public_id)[0], "full_name",
                         getattr(resolve_person(p.user_public_id)[0], "username", "Unknown"))
        }
        for p in conv.participants if p.user_public_id != caller_id
    ]
    emit('group_call_started', {
        "conversation_id": conv_id,
        "from_public_id": caller_id,
        "from_name": caller_name,
        "participants": participants
    }, room=f"group_{conv_id}", include_self=False)

@socketio.on('group_call_signal')
def group_call_signal(data):
    to_pub = data.get("to_public_id")
    group_id = data.get("group_id")
    payload = {
        "conversation_id": data.get("conversation_id"),
        "signal_type": data.get("signal_type"),
        "signal_data": data.get("signal_data"),
        "sender_public_id": data.get("sender_public_id"),
        "to_public_id": to_pub
    }
    if to_pub:
        emit('group_call_signal', payload, room=f"user_{to_pub}")
    else:
        emit('group_call_signal', payload, room=f"group_{group_id}", include_self=False)

@socketio.on('join_group_call_room')
def join_group_room(data):
    conv_id = data.get("conversation_id")
    if conv_id:
        join_room(f"group_{conv_id}")

@socketio.on('group_call_end')
def group_call_end(data):
    conv_id = data.get("conversation_id")
    if conv_id:
        emit('group_call_ended', {
            "conversation_id": conv_id,
            "from_public_id": current_user.public_id
        }, room=f"group_{conv_id}")