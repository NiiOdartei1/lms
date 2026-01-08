from flask import current_app, url_for
from flask_mailman import EmailMessage


def send_email(to_email, subject, body):
    """
    Send an email using Flask-Mailman.
    """
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=current_app.config['MAIL_DEFAULT_SENDER'],
        to=[to_email]
    )
    msg.send()  # ✅ send directly


def send_password_reset_email(user, token):
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    subject = "Password Reset Request"
    body = f"""
    Hello {user.full_name},

    A request was received to reset your password.
    Click the link below to set a new password (expires in 1 hour):

    {reset_url}

    If you did not request this, please ignore this email.
    """
    send_email(user.email, subject, body)


def send_temporary_password_email(user, temp_password):
    subject = "Your Temporary Password"
    body = f"""
    Hello {user.full_name},

    An administrator has reset your password.
    Your temporary password is:

    {temp_password}

    Please log in and change your password immediately.
    """
    send_email(user.email, subject, body)
