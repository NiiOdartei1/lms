# test_mail.py
from flask import Flask
from flask_mailman import Mail, EmailMessage

app = Flask(__name__)

app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='lampteyjoseph860@gmail.com',
    MAIL_PASSWORD='injj jivj dnlq tlum',
    MAIL_DEFAULT_SENDER=('LMS Admin', 'lampteyjoseph860@gmail.com')
)

mail = Mail(app)

with app.app_context():
    msg = EmailMessage(
        subject='SMTP Test',
        body='This is a test email from Flask.',
        to=['your_other_email@gmail.com']
    )
    msg.send()
    print("✅ Test email sent!")
