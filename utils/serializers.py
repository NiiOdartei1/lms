def serialize_admin(admin):
    return {
        'id': admin.id,
        'username': admin.username,
        'admin_id': admin.admin_id
    }

def serialize_user(user):
    return {
        'user_id': user.user_id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role
    }

def serialize_student(s):
    return {
        'user_id': s.user_id,
        'current_class': s.current_class,
        'guardian_name': s.guardian_name,
        'guardian_contact': s.guardian_contact
    }

def serialize_quiz(q):
    return {
        'id': q.id,
        'title': q.title,
        'assigned_class': q.assigned_class,
        'date': q.date.strftime('%Y-%m-%d') if q.date else '',
        'duration_minutes': q.duration_minutes
    }

def serialize_question(q):
    return {
        'id': q.id,
        'quiz_id': q.quiz_id,
        'question_text': '',
        'marks': ''
    }

def serialize_option(o):
    return {
        'id': o.id,
        'question_id': o.question_id,
        'option_text': '',
        'is_correct': o.is_correct
    }

def serialize_submission(sub):
    return {
        "id": sub.id,
        "student_id": sub.student_id,
        "student_username": sub.student.username if sub.student else "N/A",
        "quiz_title": sub.quiz.title if sub.quiz else "N/A",
        "score": sub.score,
        "submitted_at": sub.submitted_at.strftime("%Y-%m-%d %H:%M:%S")
    }

def serialize_message(m):
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "content": m.content,
        "created_at": m.created_at.isoformat(),

        # 🔥 REQUIRED
        "sender_id": m.sender_id,
        "sender_role": m.sender_role,
        "sender_name": m.sender_name,  # MUST be resolved from role table
    }
