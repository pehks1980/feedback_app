from datetime import datetime, timedelta, timezone
from flask import Flask, request, render_template, redirect, url_for
import sqlite3
import uuid
import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

limiter.init_app(app)

# Configuration from environment variables
DOMAIN = os.getenv("DOMAIN", "127.0.0.1:8080")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
EXPIRE_DAYS = 14

# Database path in the data directory
DB_PATH ='./data/feedback.db'
ADMIN_LINK_PATH = './data/db_admin_link'
#language
RU='ru' #'' for default

def init_db():
    """Initialize database and create admin user if needed"""
    print(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create tables
    c.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            employer_id TEXT,
            company_name TEXT,
            role TEXT,
            expires_at TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT,
            reason TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Check if admin already exists
    c.execute("SELECT id FROM requests WHERE role='admin'")
    admin = c.fetchone()

    if not admin:
        admin_id = str(uuid.uuid4())

        c.execute(
            "INSERT INTO requests (id, employer_id, company_name, role, expires_at) VALUES (?, ?, ?, ?, ?)",
            (admin_id, "0", "admin_panel", "admin", None)
        )

        # Create admin link
        link = (f'=== ADMIN LINK ===\n'
                f'http://{DOMAIN}/feedback/{admin_id}\n'
                f'==================\n')
        print(link)

        # Save admin link to file in data directory
        with open(ADMIN_LINK_PATH, 'w') as f:
            f.write(link)

    conn.commit()
    conn.close()


@app.route('/admin', methods=['POST'])
@limiter.limit("10 per minute")
def admin():
    if request.method == 'POST':
        employer_id = request.form['employer_id']
        company_name = request.form['company_name']

        req_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                  (req_id, employer_id, company_name, "user", expires_at))
        conn.commit()
        conn.close()

        link = f"http://{DOMAIN}/feedback/{req_id}"
        print(link)
        return render_template(f"{RU}fblink.html", link=link)

    return render_template(f'{RU}success.html')


@app.route('/feedback/<req_id>')
@limiter.limit("60 per minute")
def landing(req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT company_name, role, expires_at FROM requests WHERE id=?", (req_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Invalid link"

    company_name, role, expires_at = row

    # Expiration check
    if expires_at:
        expires_at_dt = datetime.fromisoformat(expires_at)
        expires_pretty = expires_at_dt.strftime("%B %d, %Y at %H:%M UTC")

        # Make timezone-aware if needed
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at_dt:
            conn.close()
            return render_template(f"{RU}expired.html")

    # Admin view
    if role == "admin":
        c.execute('''
            SELECT r.created_at, q.company_name, q.employer_id, r.reason, r.comment
            FROM responses r
            JOIN requests q ON r.request_id = q.id
            ORDER BY r.created_at DESC
        ''')
        rows = c.fetchall()
        conn.close()
        return render_template('admin.html', rows=rows)

    conn.close()
    return render_template(f'{RU}landing.html', req_id=req_id, company_name=company_name, expires_at=expires_pretty)


@app.route('/form/<req_id>')
@limiter.limit("10 per minute")
def form(req_id):
    return render_template(f'{RU}form.html', req_id=req_id)


@app.route('/submit', methods=['POST'])
@limiter.limit("10 per minute")
def submit():
    req_id = request.form.get('req_id')
    reason = request.form.get('reason')
    comment = request.form.get('comment', '').strip()

    # Validations
    if not req_id:
        return "Error: Request ID is missing", 400

    if not reason:
        return "Error: Please select a reason", 400

    valid_reasons = ['experience', 'better_candidate', 'salary', 'stack', 'other']
    if reason not in valid_reasons:
        return "Error: Invalid reason selected", 400

    if len(comment) > 1000:
        return "Error: Comment is too long (max 1000 characters)", 400

    if reason == 'other' and not comment:
        return "Error: Please provide details when selecting 'Other'", 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO responses (request_id, reason, comment) VALUES (?, ?, ?)",
              (req_id, reason, comment))
    conn.commit()
    conn.close()

    return render_template(f'{RU}success.html')

@app.route('/debug/env')
@limiter.limit("10 per minute")
def debug_env():
    return {
        'DOMAIN': DOMAIN,
        'FLASK_DEBUG': FLASK_DEBUG,
        'RU': RU
    }

if os.path.exists(ADMIN_LINK_PATH):
    with open(ADMIN_LINK_PATH, 'r') as f:
        print(f.read())
if not os.path.exists(DB_PATH):
    init_db()

#app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)



