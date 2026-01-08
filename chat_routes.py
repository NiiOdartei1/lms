from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from flask_socketio import emit, join_room
from utils.extensions import db, socketio
from models import Admin, Conversation, ConversationParticipant, Message, MessageReaction, SchoolClass, User, ParentChildLink
from datetime import datetime
import json

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')

# -------------------------
# Helper functions
# -------------------------
def resolve_person_by_public_id(pub_id):
    """Return (model_instance, role_string) or (None, None)."""
    if not pub_id:
        return None, None
    person = User.query.filter_by(public_id=pub_id).first()
    if person:
        return person, getattr(person, "role", "user")
    admin = Admin.query.filter_by(public_id=pub_id).first()
    if admin:
        return admin, "admin"
    return None, None

def add_participant_if_not_exists(conv_id, person_or_public_id, role=None):
    """
    Accept either a User/Admin instance (preferred) OR a public_id string (for external callers).
    Adds a ConversationParticipant row keyed by user_public_id.
    """
    if not person_or_public_id:
        return

    if hasattr(person_or_public_id, 'public_id'):
        user_public_id = getattr(person_or_public_id, 'public_id')
        user_role = role or getattr(person_or_public_id, 'role', 'user')
    else:
        user_public_id = str(person_or_public_id)
        if role:
            user_role = role
        else:
            resolved_person, resolved_role = resolve_person_by_public_id(user_public_id)
            user_role = resolved_role or 'user'

    exists = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=user_public_id
    ).first()
    if not exists:
        db.session.add(ConversationParticipant(
            conversation_id=conv_id,
            user_public_id=user_public_id,
            user_role=user_role
        ))

def conversation_to_dict(conv, current_user_pubid):
    participants = []
    for p in conv.participants:
        person, _ = resolve_person_by_public_id(p.user_public_id)
        display_name = getattr(
            person,
            "full_name",
            getattr(person, "username", "Unknown")
        ) if person else "Unknown"

        participants.append({
            "user_public_id": p.user_public_id,
            "role": p.user_role,
            "name": display_name
        })

    last_message = conv.messages[-1].to_dict() if conv.messages else None

    last_read_at = next(
        (p.last_read_at for p in conv.participants
         if p.user_public_id == current_user_pubid),
        None
    ) or datetime.min

    unread_count = sum(
        1 for m in conv.messages
        if (m.created_at or datetime.min) > last_read_at
    )

    meta = conv.get_meta() or {}

    created_by_pub = meta.get("created_by")
    created_by_name = None
    if created_by_pub:
        creator, _ = resolve_person_by_public_id(created_by_pub)
        if creator:
            created_by_name = getattr(
                creator,
                "full_name",
                getattr(creator, "username", "Unknown")
            )

    return {
        "id": conv.id,
        "type": conv.type,
        "name": meta.get("name"),
        "created_by": created_by_pub,          # ✅ public id
        "created_by_name": created_by_name,    # ✅ display name
        "participants": participants,
        "last_message": last_message,
        "unread_count": unread_count,
        "updated_at": conv.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }

def require_group_admin(conv_id):
    p = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id,
        is_group_admin=True
    ).first()
    return p

# ───────────────
# Track online users
# ───────────────
online_users = set()
sid_to_pub = {}

# -----------------------------
# SocketIO events
# -----------------------------
from flask_socketio import disconnect

@socketio.on('join')
def on_join(data):
    # client should emit { user_id: "<public_id>" } but we also try current_user
    pub = (data or {}).get('user_id') or getattr(current_user, 'public_id', None)
    if not pub:
        return

    sid = request.sid
    sid_to_pub[sid] = pub

    online_users.add(pub)
    join_room(f"user_{pub}")

    # notify all clients (no broadcast kwarg)
    socketio.emit('presence_update', {'user_public_id': pub, 'status': 'online'})

@socketio.on('disconnect')
def on_disconnect():
    # request.sid is the disconnected client's sid
    sid = request.sid
    pub = sid_to_pub.pop(sid, None)

    # fallback: attempt current_user.public_id if available
    if not pub:
        pub = getattr(current_user, 'public_id', None)

    if pub and pub in online_users:
        online_users.remove(pub)

        # Update last_seen in database
        person, _ = resolve_person_by_public_id(pub)
        if person:
            person.last_seen = datetime.utcnow()
            db.session.commit()

        socketio.emit(
            'presence_update',
            {
                'user_public_id': pub,
                'status': 'offline',
                'last_seen': datetime.utcnow().isoformat()
            }
        )

@socketio.on('send_message')
def handle_message(data):
    """
    Socket event for realtime messages.
    Expected data: { conversation_id: int, message: string, reply_to_message_id: int (optional) }
    """
    conv_id = data.get('conversation_id')
    message_text = data.get('message')
    reply_to_message_id = data.get('reply_to_message_id')
    if not conv_id or not message_text:
        return
    sender_pub = getattr(current_user, 'public_id', None)
    msg = Message(
        conversation_id=conv_id,
        sender_public_id=sender_pub,
        sender_role=getattr(current_user, "role", "user"),
        content=message_text,
        reply_to_message_id=reply_to_message_id,
    )
    db.session.add(msg)
    conv = Conversation.query.get(conv_id)
    if conv:
        conv.updated_at = datetime.utcnow()
    db.session.commit()

    # emit to participant rooms using user_public_id
    if conv:
        for part in conv.participants:
            room = f"user_{part.user_public_id}"
            socketio.emit('new_message', {"conversation_id": conv.id, "message": msg.to_dict()}, room=room)

# -------------------------
# Routes
# -------------------------
@chat_bp.route('/')
@login_required
def chat_home():
    return render_template('chat.html')

# -------------------------
# Routes for classes
# -------------------------
@chat_bp.route('/classes')
@login_required
def get_classes():
    """
    Returns all school classes.
    Output format: [{ "id": 1, "name": "Primary 1" }, ...]
    """
    classes = SchoolClass.query.order_by(SchoolClass.name).all()
    result = [{"id": c.id, "name": c.name} for c in classes]
    return jsonify(result), 200

@chat_bp.route('/conversations', methods=['GET'])
@login_required
def get_conversations():
    conv_participants = ConversationParticipant.query.filter_by(
        user_public_id=current_user.public_id
    ).all()
    conversations = [p.conversation for p in conv_participants]
    result = [conversation_to_dict(conv, current_user.public_id) for conv in conversations]
    return jsonify(result), 200

@chat_bp.route('/conversations/<int:conv_id>/messages', methods=['GET'])
@login_required
def get_messages(conv_id):
    conv = Conversation.query.get_or_404(conv_id)
    is_participant = ConversationParticipant.query.filter_by(conversation_id=conv_id, user_public_id=current_user.public_id).first() is not None
    is_site_admin = getattr(current_user, "role", "") == "admin" or getattr(current_user, "is_admin", False)
    if not (is_participant or is_site_admin):
        return jsonify({"error": "Access denied"}), 403
    messages = [m.to_dict() for m in conv.messages if not m.is_deleted]
    
    # Add reactions to each message
    for msg in messages:
        reactions = MessageReaction.query.filter_by(message_id=msg['id']).all()
        msg['reactions'] = [r.to_dict() for r in reactions]
    
    return jsonify(messages), 200

@chat_bp.route('/presence/<public_id>')
@login_required
def get_presence(public_id):
    if public_id in online_users:
        return jsonify({"status": "online"})

    # Get last_seen from database
    person, _ = resolve_person_by_public_id(public_id)
    if person and person.last_seen:
        return jsonify({
            "status": "offline",
            "last_seen": person.last_seen.isoformat()
        })

    # fallback: last message timestamp if no last_seen
    last_msg = Message.query.filter_by(
        sender_public_id=public_id
    ).order_by(Message.created_at.desc()).first()

    return jsonify({
        "status": "offline",
        "last_seen": last_msg.created_at.isoformat() if last_msg else None
    })

@chat_bp.route('/send_dm', methods=['POST'])
@login_required
def send_dm():
    """
    Expects JSON:
      - message (string)
      - receiver_public_id (string)
    """
    data = request.json or {}
    message_text = data.get('message')
    receiver_public_id = data.get('receiver_public_id')
    reply_to_message_id = data.get('reply_to_message_id')

    if not message_text:
        return jsonify({"success": False, "error": "Empty message"}), 400
    if not receiver_public_id:
        return jsonify({"success": False, "error": "Missing receiver_public_id"}), 400

    receiver, receiver_role = resolve_person_by_public_id(receiver_public_id)
    if not receiver:
        return jsonify({"success": False, "error": "Receiver not found"}), 404

    my_pub = current_user.public_id
    rec_pub = receiver_public_id

    if my_pub == rec_pub:
        return jsonify({
            "success": False,
            "error": "You cannot send a message to yourself."
        }), 400

    # Check if DM conversation already exists between these two public ids
    conv = Conversation.query.filter(
        Conversation.type == 'direct',
        Conversation.participants.any(ConversationParticipant.user_public_id == my_pub),
        Conversation.participants.any(ConversationParticipant.user_public_id == rec_pub)
    ).first()

    # Create conversation if not exists
    if not conv:
        conv = Conversation(type='direct', created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        db.session.add(conv)
        db.session.flush()
        add_participant_if_not_exists(conv.id, current_user)
        add_participant_if_not_exists(conv.id, receiver, role=receiver_role)
        db.session.commit()

    # Create message
    msg = Message(conversation_id=conv.id, sender_public_id=my_pub, sender_role=getattr(current_user, "role", "user"), content=message_text, reply_to_message_id=reply_to_message_id)
    db.session.add(msg)
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    # Emit to participants
    for p in conv.participants:
        room = f"user_{p.user_public_id}"
        socketio.emit('new_message', {"conversation_id": conv.id, "message": msg.to_dict()}, room=room)

    return jsonify({"success": True, "conversation_id": conv.id, "message": msg.to_dict()}), 200

@chat_bp.route('/mark_read', methods=['POST'])
@login_required
def mark_read():
    data = request.json or {}
    conversation_id = data.get('conversation_id')
    conv_part = ConversationParticipant.query.filter_by(conversation_id=conversation_id, user_public_id=getattr(current_user, 'public_id', None)).first()
    if conv_part:
        conv_part.last_read_at = datetime.utcnow()
        db.session.commit()
    return jsonify({"success": True}), 200

@chat_bp.route('/users')
@login_required
def get_users():
    role = request.args.get('role')
    class_id = request.args.get('class_id')

    if not role:
        return jsonify([])

    q = User.query.filter(
        User.role == role,
        User.id != current_user.id   # exclude self
    )

    # ONLY students are class-bound
    if role == 'student':
        if not class_id:
            return jsonify([])
        q = q.filter(User.class_id == int(class_id))

    users = q.order_by(User.first_name, User.last_name).all()

    return jsonify([
        {
            "id": u.public_id,
            "name": u.full_name
        }
        for u in users
    ])

@chat_bp.route('/conversations/<int:conv_id>/messages/<int:msg_id>/edit', methods=['POST'])
@login_required
def edit_message(conv_id, msg_id):
    conv = Conversation.query.get_or_404(conv_id)

    participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()
    if not participant:
        return jsonify({"error": "Access denied"}), 403

    msg = Message.query.filter_by(id=msg_id, conversation_id=conv_id).first_or_404()

    if msg.sender_public_id != current_user.public_id:
        return jsonify({"error": "You can only edit your own message"}), 403

    data = request.json or {}
    new_content = data.get("content", "").strip()
    if not new_content:
        return jsonify({"error": "Message cannot be empty"}), 400

    msg.content = new_content
    msg.edited_at = datetime.utcnow()
    msg.edited_by = current_user.public_id

    conv.updated_at = datetime.utcnow()
    db.session.commit()

    for p in conv.participants:
        socketio.emit(
            'message_edited',
            {"conversation_id": conv.id, "message": msg.to_dict()},
            room=f"user_{p.user_public_id}"
        )

    return jsonify({"success": True, "message": msg.to_dict()}), 200

@chat_bp.route('/conversations/<int:conv_id>/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def delete_message(conv_id, msg_id):
    conv = Conversation.query.get_or_404(conv_id)

    participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()
    if not participant:
        return jsonify({"error": "Access denied"}), 403

    msg = Message.query.filter_by(id=msg_id, conversation_id=conv_id).first_or_404()

    if msg.sender_public_id != current_user.public_id:
        return jsonify({"error": "You can only delete your own message"}), 403

    msg.is_deleted = True
    msg.deleted_at = datetime.utcnow()
    msg.deleted_by = current_user.public_id

    conv.updated_at = datetime.utcnow()
    db.session.commit()

    for p in conv.participants:
        socketio.emit(
            'message_deleted',
            {"conversation_id": conv.id, "message_id": msg.id},
            room=f"user_{p.user_public_id}"
        )

    return jsonify({"success": True}), 200

@chat_bp.route('/conversations/<int:conv_id>/messages/<int:msg_id>/copy', methods=['GET'])
@login_required
def copy_message(conv_id, msg_id):
    conv = Conversation.query.get_or_404(conv_id)

    participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()
    if not participant:
        return jsonify({"error": "Access denied"}), 403

    msg = Message.query.filter_by(id=msg_id, conversation_id=conv_id).first_or_404()

    if msg.is_deleted:
        return jsonify({"error": "Message deleted"}), 400

    return jsonify({"content": msg.content}), 200

@chat_bp.route('/conversations/<int:conv_id>/messages/<int:msg_id>/react', methods=['POST'])
@login_required
def add_reaction(conv_id, msg_id):
    data = request.json or {}
    emoji = data.get('emoji')
    if not emoji:
        return jsonify({"error": "Emoji required"}), 400

    # Check access
    participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()
    if not participant:
        return jsonify({"error": "Access denied"}), 403

    msg = Message.query.filter_by(id=msg_id, conversation_id=conv_id).first_or_404()

    # Check if reaction already exists
    existing = MessageReaction.query.filter_by(
        message_id=msg_id,
        user_public_id=current_user.public_id,
        emoji=emoji
    ).first()
    if existing:
        return jsonify({"error": "Already reacted"}), 400

    reaction = MessageReaction(
        message_id=msg_id,
        user_public_id=current_user.public_id,
        emoji=emoji
    )
    db.session.add(reaction)
    db.session.commit()

    # Emit to all participants
    participants = ConversationParticipant.query.filter_by(conversation_id=conv_id).all()
    for p in participants:
        socketio.emit(
            "reaction_added",
            {"message_id": msg_id, "reaction": reaction.to_dict()},
            room=f"user_{p.user_public_id}"
        )

    return jsonify({"success": True, "reaction": reaction.to_dict()}), 200

@chat_bp.route('/conversations/<int:conv_id>/messages/<int:msg_id>/react', methods=['DELETE'])
@login_required
def remove_reaction(conv_id, msg_id):
    data = request.json or {}
    emoji = data.get('emoji')
    if not emoji:
        return jsonify({"error": "Emoji required"}), 400

    # Check access
    participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()
    if not participant:
        return jsonify({"error": "Access denied"}), 403

    reaction = MessageReaction.query.filter_by(
        message_id=msg_id,
        user_public_id=current_user.public_id,
        emoji=emoji
    ).first_or_404()

    db.session.delete(reaction)
    db.session.commit()

    # Emit to all participants
    participants = ConversationParticipant.query.filter_by(conversation_id=conv_id).all()
    for p in participants:
        socketio.emit(
            "reaction_removed",
            {"message_id": msg_id, "user_public_id": current_user.public_id, "emoji": emoji},
            room=f"user_{p.user_public_id}"
        )

    return jsonify({"success": True}), 200

@chat_bp.route(
    '/conversations/<int:conv_id>/messages/<int:msg_id>/forward',
    methods=['POST']
)
@login_required
def forward_message(conv_id, msg_id):
    data = request.get_json(silent=True) or {}
    target_conv_id = data.get("target_conversation_id")

    if not target_conv_id:
        return jsonify({"error": "Missing target_conversation_id"}), 400

    # ── Fetch conversations
    source_conv = Conversation.query.get_or_404(conv_id)
    target_conv = Conversation.query.get_or_404(target_conv_id)

    # ── Permission: must be participant in BOTH conversations
    is_source_participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first()

    is_target_participant = ConversationParticipant.query.filter_by(
        conversation_id=target_conv_id,
        user_public_id=current_user.public_id
    ).first()

    if not is_source_participant or not is_target_participant:
        return jsonify({"error": "Access denied"}), 403

    # ── Message must belong to source conversation
    msg = Message.query.filter_by(
        id=msg_id,
        conversation_id=conv_id
    ).first_or_404()

    if msg.is_deleted:
        return jsonify({"error": "Message deleted"}), 400

    # ── Create forwarded copy (sender = current user)
    new_msg = Message(
        conversation_id=target_conv.id,
        sender_public_id=current_user.public_id,
        sender_role=getattr(current_user, "role", "user"),
        content=msg.content
    )

    db.session.add(new_msg)
    target_conv.updated_at = datetime.utcnow()
    db.session.commit()

    # ── Realtime notify all participants in target conversation
    for p in target_conv.participants:
        socketio.emit(
            'new_message',
            {
                "conversation_id": target_conv.id,
                "message": new_msg.to_dict()
            },
            room=f"user_{p.user_public_id}"
        )

    return jsonify({"success": True}), 200

# Group chat routes
@chat_bp.route('/conversations/group/create', methods=['POST'])
@login_required
def create_group():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    members = data.get('members', [])

    if not name or not members:
        return jsonify({'error': 'Invalid input'}), 400

    # Create group conversation
    conv = Conversation(type='group')
    conv.set_meta({
        "name": name,
        "created_by": current_user.public_id,
        "admins": [current_user.public_id]
    })

    db.session.add(conv)
    db.session.flush()

    # Add creator (admin)
    add_participant_if_not_exists(conv.id, current_user)

    # Add selected members
    for pub_id in members:
        person, role = resolve_person_by_public_id(pub_id)
        if person:
            add_participant_if_not_exists(conv.id, person, role)

    db.session.commit()

    return jsonify(conversation_to_dict(conv, current_user.public_id)), 200

@chat_bp.route('/groups/<int:conv_id>/rename', methods=['POST'])
@login_required
def rename_group(conv_id):
    admin = require_group_admin(conv_id)
    if not admin or not admin.can_rename_group:
        return jsonify({"error": "Permission denied"}), 403

    data = request.json or {}
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"error": "Name required"}), 400

    conv = Conversation.query.get_or_404(conv_id)
    meta = conv.get_meta()
    meta["name"] = name
    conv.set_meta(meta)

    db.session.commit()
    return jsonify({"success": True})

@chat_bp.route('/groups/<int:conv_id>/add_member', methods=['POST'])
@login_required
def add_group_member(conv_id):
    admin = require_group_admin(conv_id)
    if not admin or not admin.can_add_members:
        return jsonify({"error": "Permission denied"}), 403

    data = request.json or {}
    pub_id = data.get("user_public_id")

    person, role = resolve_person_by_public_id(pub_id)
    if not person:
        return jsonify({"error": "User not found"}), 404

    add_participant_if_not_exists(conv_id, person, role)
    db.session.commit()

    return jsonify({"success": True})

@chat_bp.route('/groups/<int:conv_id>/remove_member', methods=['POST'])
@login_required
def remove_group_member(conv_id):
    admin = require_group_admin(conv_id)
    if not admin or not admin.can_remove_members:
        return jsonify({"error": "Permission denied"}), 403

    data = request.json or {}
    pub_id = data.get("user_public_id")

    ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=pub_id
    ).delete()

    db.session.commit()
    return jsonify({"success": True})

@chat_bp.route('/conversations/<int:conv_id>/messages', methods=['POST'])
@login_required
def post_conversation_message(conv_id):
    data = request.get_json(silent=True) or {}
    message_text = (data.get('message') or '').strip()
    reply_to_message_id = data.get('reply_to_message_id')

    if not message_text:
        return jsonify({"success": False, "error": "Empty message"}), 400

    conv = Conversation.query.get_or_404(conv_id)

    is_participant = ConversationParticipant.query.filter_by(
        conversation_id=conv_id,
        user_public_id=current_user.public_id
    ).first() is not None

    is_site_admin = getattr(current_user, "role", "") == "admin" or getattr(current_user, "is_admin", False)

    if not (is_participant or is_site_admin):
        return jsonify({"success": False, "error": "Access denied"}), 403

    # ✅ Validate reply target
    if reply_to_message_id:
        parent = Message.query.filter_by(
            id=reply_to_message_id,
            conversation_id=conv_id
        ).first()
        if not parent:
            return jsonify({"success": False, "error": "Invalid reply target"}), 400

    msg = Message(
        conversation_id=conv.id,
        sender_public_id=current_user.public_id,
        sender_role=getattr(current_user, "role", "user"),
        content=message_text,
        reply_to_message_id=reply_to_message_id   # ✅ FIX
    )

    db.session.add(msg)
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    for p in conv.participants:
        socketio.emit(
            'new_message',
            {"conversation_id": conv.id, "message": msg.to_dict()},
            room=f"user_{p.user_public_id}"
        )

    return jsonify({
        "success": True,
        "conversation_id": conv.id,
        "message": msg.to_dict()
    }), 200

@chat_bp.route('/conversations/<int:conv_id>/add_members', methods=['POST'])
@login_required
def add_members_to_group(conv_id):
    conv = Conversation.query.get_or_404(conv_id)
    if conv.type != 'group':
        return jsonify({"success": False, "error": "Not a group conversation"}), 400

    # Check if current user is participant or admin
    is_participant = any(p.user_public_id == current_user.public_id for p in conv.participants)
    is_site_admin = getattr(current_user, "role", "") == "admin" or getattr(current_user, "is_admin", False)
    if not (is_participant or is_site_admin):
        return jsonify({"success": False, "error": "Access denied"}), 403

    data = request.get_json()
    member_ids = data.get('members', [])
    if not member_ids:
        return jsonify({"success": False, "error": "No members specified"}), 400

    added = []
    for user_id in member_ids:
        person, role = resolve_person_by_public_id(str(user_id))
        if not person:
            continue
        # Check if already participant
        exists = ConversationParticipant.query.filter_by(
            conversation_id=conv_id,
            user_public_id=str(user_id)
        ).first()
        if not exists:
            db.session.add(ConversationParticipant(
                conversation_id=conv_id,
                user_public_id=str(user_id),
                user_role=role
            ))
            added.append(str(user_id))

    db.session.commit()

    # Create a system message in the group
    added_names = []
    for uid in added:
        person, _ = resolve_person_by_public_id(uid)
        if person:
            added_names.append(getattr(person, 'display_name', getattr(person, 'username', uid)))

    if added_names:
        msg = Message(
            conversation_id=conv.id,
            sender_public_id=current_user.public_id,
            sender_role=getattr(current_user, "role", "user"),
            content=f"{getattr(current_user, 'display_name', getattr(current_user, 'username', 'Someone'))} added {', '.join(added_names)} to the group"
        )
        db.session.add(msg)
        db.session.commit()

        # Notify all participants in the group
        for p in conv.participants:
            socketio.emit(
                'new_message',
                {"conversation_id": conv.id, "message": msg.to_dict()},
                room=f"user_{p.user_public_id}"
            )

    return jsonify({"success": True, "added": added}), 200

@chat_bp.route("/call/<target_id>")
@login_required
def call_window(target_id):
    # you can pass caller_name from DB
    caller = User.query.filter_by(public_id=target_id).first()
    caller_name = caller.full_name if caller else "Unknown"
    return render_template("call_window.html", caller_name=caller_name)
