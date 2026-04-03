from datetime import datetime, timedelta, timezone

from flask import Flask, request, render_template, redirect, url_for
import sqlite3
import uuid
import os

app = Flask(__name__)
#set for link
DOMAIN = os.getenv("DOMAIN", "127.0.0.1:5000")
# set debug/prod (if env var is true - result is true with "true" so
# app var sets true otherwise falls to false
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
#set link age days
EXPIRE_DAYS = 14

def init_db():
    conn = sqlite3.connect('feedback.db')
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

    # 🔐 Check if admin already exists
    c.execute("SELECT id FROM requests WHERE role='admin'")
    admin = c.fetchone()

    if not admin:
        import uuid
        admin_id = str(uuid.uuid4())

        c.execute(
            "INSERT INTO requests (id, employer_id, company_name, role, expires_at) VALUES (?, ?, ?, ?, ?)",
            (admin_id, "0", "admin_panel", "admin", None)
        )

        link = (f'=== ADMIN LINK ===\n'
                f'http://{DOMAIN}/feedback/{admin_id}\n'
                f'==================\n')
        print(link)
        with open('db_admin_link', 'w') as f:
            f.write(link)

    conn.commit()
    conn.close()

@app.route('/admin', methods=['POST'])
def admin():
    if request.method == 'POST':
        employer_id = request.form['employer_id']
        company_name = request.form['company_name']

        req_id = str(uuid.uuid4())

        expires_at = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS) # - timedelta(seconds=10)

        conn = sqlite3.connect('feedback.db')
        c = conn.cursor()

        c.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                  (req_id, employer_id, company_name, "user", expires_at))

        conn.commit()
        conn.close()

        link = f"http://{DOMAIN}/feedback/{req_id}"

        print(link)
        return render_template("fblink.html", link=link)

    return render_template('success.html')

@app.route('/feedback/<req_id>')
def landing(req_id):
    conn = sqlite3.connect('feedback.db')
    c = conn.cursor()

    c.execute("SELECT company_name, role, expires_at FROM requests WHERE id=?", (req_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Invalid link"

    company_name, role, expires_at = row

    # expiration check
    if expires_at:
        expires_at_dt = datetime.fromisoformat(expires_at)
        expires_pretty = expires_at_dt.strftime("%B %d, %Y at %H:%M UTC")
        # make timezone-aware if needed
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at_dt:
            conn.close()
            return render_template("expired.html")

    # 🔥 HERE is your switch
    if role == "admin":
        #GET
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
    return render_template('landing.html', req_id=req_id, company_name=company_name, expires_at=expires_pretty)

@app.route('/form/<req_id>')
def form(req_id):
    return render_template('form.html', req_id=req_id)

@app.route('/submit', methods=['POST'])
def submit():
    req_id = request.form.get('req_id')
    reason = request.form.get('reason')
    comment = request.form.get('comment', '').strip()

    # Validation 1: Check if req_id exists
    if not req_id:
        return "Error: Request ID is missing", 400

    # Validation 2: Check if reason was selected (required)
    if not reason:
        return "Error: Please select a reason", 400

    # Validation 3: Check if reason is valid (optional but recommended)
    valid_reasons = ['experience', 'better_candidate', 'salary', 'stack', 'other']
    if reason not in valid_reasons:
        return "Error: Invalid reason selected", 400

    # Validation 4: Optional - comment length limit
    if len(comment) > 1000:  # Adjust limit as needed
        return "Error: Comment is too long (max 1000 characters)", 400

    # Validation 5: Optional - prevent empty "other" without comment
    if reason == 'other' and not comment:
        return "Error: Please provide details when selecting 'Other'", 400

    conn = sqlite3.connect('feedback.db')
    c = conn.cursor()
    c.execute("INSERT INTO responses (request_id, reason, comment) VALUES (?, ?, ?)",
              (req_id, reason, comment))
    conn.commit()
    conn.close()

    return render_template('success.html')

def main():
    if os.path.exists('db_admin_link'):
        with open('db_admin_link', 'r') as f:
            print(f.read())
    if not os.path.exists('feedback.db'):
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)

if __name__ == '__main__':
    main()

