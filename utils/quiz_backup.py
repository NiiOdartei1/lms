import os
import json
from datetime import datetime

def generate_quiz_backup_file(quiz_data, questions_data, backup_dir='quiz_backups'):
    os.makedirs(backup_dir, exist_ok=True)

    backup = {
        'quiz': quiz_data,
        'questions': questions_data,
        'created_at': datetime.utcnow().isoformat()
    }

    filename = f"{quiz_data['title'].replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
    filepath = os.path.join(backup_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(backup, f, indent=2)

    return filepath
