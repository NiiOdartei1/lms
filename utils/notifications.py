# utils/notifications.py
from datetime import datetime
import json
from models import SchoolClass, db, Notification, NotificationRecipient, User, StudentProfile
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

def create_fee_notification(fee_group, sender=None):
    """
    Create a notification for a fee assignment.

    Args:
        fee_group: ClassFeeStructure object
        sender: User/Admin object creating the notification. Defaults to current_user.
    """
    if sender is None:
        sender = current_user

    # Determine sender_id and type
    if hasattr(sender, 'admin_id'):
        sender_id = sender.admin_id
        sender_type = 'admin'
    elif hasattr(sender, 'user_id'):
        sender_id = sender.user_id
        sender_type = 'user'
    else:
        sender_id = None
        sender_type = 'system'

    # Parse items if stored as JSON
    items = fee_group.items
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    # Build message text
    items_text = '\n'.join([f"  • {item['description']}: {item['amount']} GHS" for item in items])
    message = (
        f"A new fee has been assigned for your class {fee_group.class_level}.\n\n"
        f"Academic Year: {fee_group.academic_year}\n"
        f"Semester: {fee_group.semester}\n"
        f"Description: {fee_group.description}\n"
        f"Total Amount: {fee_group.amount} GHS\n\n"
        f"Breakdown:\n{items_text}\n\n"
        f"Please check your Fees section for details."
    )

    # Create Notification object
    notification = Notification(
        type='fee',
        title=f'New Fee Assigned: {fee_group.description}',
        message=message,
        sender_id=sender_id,
        sender_type=sender_type,
        related_type='fee',
        related_id=fee_group.id,
        created_at=datetime.utcnow()
    )
    db.session.add(notification)
    db.session.flush()  # Get notification.id

    # Map class_level string to SchoolClass
    school_class = SchoolClass.query.filter_by(name=fee_group.class_level).first()
    if not school_class:
        db.session.rollback()
        raise ValueError(f"No class found matching '{fee_group.class_level}'")

    # Get all students in the class
    students = User.query.filter_by(class_id=school_class.id, role='student').all()

    # Create recipients for students and optionally parents
    for student in students:
        # Notify student
        db.session.add(NotificationRecipient(
            notification_id=notification.id,
            user_id=student.user_id,
            is_read=False
        ))

        # Notify parents if you have a relationship student.parents
        if hasattr(student, 'parents'):
            for parent in student.parents:
                db.session.add(NotificationRecipient(
                    notification_id=notification.id,
                    user_id=parent.user_id,
                    is_read=False
                ))

    db.session.commit()

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
