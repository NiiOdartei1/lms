# utils/backup.py
import csv
import os
from datetime import datetime
from models import StudentProfile, User  # adjust import if models are elsewhere

def generate_quiz_csv_backup(quiz_data, questions_data, backup_dir='backups'):
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    csv_filename = f"quiz_backup_{quiz_data['title'].replace(' ', '_')}_{timestamp}.csv"
    csv_path = os.path.join(backup_dir, csv_filename)

    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # Write metadata first
        writer.writerow(['Title', 'Subject', 'Assigned Class', 'Start', 'End', 'Duration', 'Attempts', 'Content File'])
        writer.writerow([
            quiz_data['title'],
            quiz_data['subject'],
            quiz_data['assigned_class'],
            quiz_data['start_datetime'],
            quiz_data['end_datetime'],
            quiz_data['duration_minutes'],
            quiz_data['attempts_allowed'],
            quiz_data['content_file']
        ])
        writer.writerow([])  # Blank line
        writer.writerow(['Question', 'Option Text', 'Is Correct'])

        # Write each question and its options
        for q in questions_data:
            for opt in q['options']:
                writer.writerow([q['text'], opt['text'], 'Yes' if opt['is_correct'] else 'No'])

    return csv_path

def backup_students_to_csv(backup_dir='backups'):
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    filename = f'student_backup_{timestamp}.csv'
    path = os.path.join(backup_dir, filename)

    students = StudentProfile.query.all()

    with open(path, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['User ID', 'Full Name', 'Email', 'Current Class', 'Gender', 'Date of Birth'])

        for s in students:
            writer.writerow([
                s.user_id,
                s.user.full_name,
                s.user.email,
                s.current_class,
                s.gender,
                s.date_of_birth.strftime('%Y-%m-%d') if s.date_of_birth else '',
            ])

    return filename
