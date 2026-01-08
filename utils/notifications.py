# utils/notifications.py
from datetime import datetime
from models import db, Notification, NotificationRecipient, User, StudentProfile
from flask_login import current_user

def create_assignment_notification(assignment):
    """
    Create a notification for a new assignment and send to all students in the assigned class.
    The notification message includes date + time.
    """
    # format due date with time
    due_str = assignment.due_date.strftime('%d %B %Y, %I:%M %p') if assignment.due_date else 'No due date'

    notice = Notification(
        type='assignment',
        title=f"New Assignment: {assignment.title}",
        message=(
            f"A new assignment has been posted for {assignment.course_name}.\n\n"
            f"Due Date: {due_str}\n\n"
            f"Please check the Assignments section."
        ),
        created_at=datetime.utcnow(),
        related_type='assignment',
        related_id=assignment.id,
        # store sender as current_user.user_id when available (user or teacher)
        sender_id=getattr(current_user, 'user_id', None) or getattr(current_user, 'admin_id', None)
    )

    db.session.add(notice)
    db.session.flush()  # get notice.id

    # Find all students in the assigned class (use student.user_id)
    students = User.query.join(StudentProfile).filter(
        StudentProfile.current_class == assignment.assigned_class
    ).all()

    recipients = [
        NotificationRecipient(notification_id=notice.id, user_id=s.user_id)
        for s in students if s.user_id
    ]
    if recipients:
        db.session.add_all(recipients)

    db.session.commit()
    return notice

def create_fee_notification(fee):
    """
    Create a notification when a new fee is assigned.
    Sends notification to all students and parents of that class.
    """
    notice = Notification(
        type='fee',
        title=f"New Fee Assigned: {fee.description}",
        message=(
            f"A new fee has been assigned for your class {fee.class_level}.\n\n"
            f"Academic Year: {fee.academic_year}\n"
            f"Semester: {fee.semester}\n"
            f"Description: {fee.description}\n"
            f"Amount: {fee.amount:.2f} GHS\n\n"
            f"Please check your Fees section for details."
        ),
        created_at=datetime.utcnow(),
        related_type='fee',
        related_id=fee.id,
        sender_id=getattr(current_user, 'user_id', None) or getattr(current_user, 'admin_id', None)
    )

    db.session.add(notice)
    db.session.flush()  # get notice.id

    # 🔹 Students in the assigned class
    students = User.query.join(StudentProfile).filter(
        StudentProfile.current_class == fee.class_level
    ).all()

    recipients = []

    for student in students:
        if student.user_id:
            # Add student
            recipients.append(NotificationRecipient(notification_id=notice.id, user_id=student.user_id))

            # Add parents
            if hasattr(student, 'parent_id') and student.parent_id:
                parent = User.query.filter_by(user_id=student.parent_id).first()
                if parent:
                    recipients.append(NotificationRecipient(notification_id=notice.id, user_id=parent.user_id))

    if recipients:
        db.session.add_all(recipients)

    db.session.commit()
    return notice

def create_missed_call_notification(caller_name, target_user_id, conversation_id):
    """
    Create a notification for a missed call when the target user is not online.
    """
    notice = Notification(
        type='call',
        title="Missed Call",
        message=f"You missed a call from {caller_name}.",
        created_at=datetime.utcnow(),
        related_type='conversation',
        related_id=conversation_id,
        sender_id=getattr(current_user, 'user_id', None) or getattr(current_user, 'admin_id', None)
    )

    db.session.add(notice)
    db.session.flush()  # get notice.id

    # Send to the target user
    recipient = NotificationRecipient(notification_id=notice.id, user_id=target_user_id)
    db.session.add(recipient)

    db.session.commit()
    return notice
