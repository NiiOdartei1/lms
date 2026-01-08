import sqlite3
import os
from app import app

print("Current directory:", os.getcwd())
print("Database URI:", app.config.get('SQLALCHEMY_DATABASE_URI'))

# Extract database path from URI
db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
if db_uri.startswith('sqlite:///'):
    db_path = db_uri[10:]  # Remove 'sqlite:///'
else:
    db_path = 'lms.db'

print("Database path:", db_path)
print("Database file exists:", os.path.exists(db_path))

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", tables)

# Check if message table exists and its columns
cursor.execute("PRAGMA table_info(message)")
columns = cursor.fetchall()
print("Message table columns:", columns)

conn.close()