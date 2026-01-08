# utils/parent_child_helpers.py
from flask import abort
from flask_login import current_user
from models import StudentProfile, ParentProfile, User

def check_parent_access(student_profile_id):
    if current_user.role != 'parent':
        abort(403)

    parent_profile = ParentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    linked_ids = [link.student.id for link in parent_profile.children_links]
    if student_profile_id not in linked_ids:
        abort(403)

    student_profile = StudentProfile.query.get_or_404(student_profile_id)
    student_user = User.query.filter_by(user_id=student_profile.user_id).first_or_404()

    return student_profile, student_user
