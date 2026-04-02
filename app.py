from flask import Flask, request, render_template, redirect, url_for
import sqlite3
import uuid
import os

app = Flask(__name__)

DOMAIN="127.0.0.1:5000" #testing

def init_db():
    conn = sqlite3.connect('feedback.db')
    c = conn.cursor()

    # Create tables
    c.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            employer_id TEXT,
            company_name TEXT,
            role TEXT
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
            "INSERT INTO requests VALUES (?, ?, ?, ?)",
            (admin_id, "0", "admin_panel", "admin")
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

        conn = sqlite3.connect('feedback.db')
        c = conn.cursor()

        c.execute("INSERT INTO requests VALUES (?, ?, ?, ?)",
                  (req_id, employer_id, company_name, "user"))

        conn.commit()
        conn.close()

        link = f"http://{DOMAIN}/feedback/{req_id}"

        print(link)

        return f"Generated link:<br><a href='{link}'>{link}</a>"

    return render_template('success.html')

@app.route('/feedback/<req_id>')
def landing(req_id):
    conn = sqlite3.connect('feedback.db')
    c = conn.cursor()
    c.execute("SELECT company_name, role FROM requests WHERE id=?", (req_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Invalid link"

    company_name, role = row

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
    return render_template('landing.html', req_id=req_id, company_name=company_name)

@app.route('/form/<req_id>')
def form(req_id):
    return render_template('form.html', req_id=req_id)

@app.route('/submit', methods=['POST'])
def submit():
    req_id = request.form['req_id']
    reason = request.form['reason']
    comment = request.form['comment']

    conn = sqlite3.connect('feedback.db')
    c = conn.cursor()
    c.execute("INSERT INTO responses (request_id, reason, comment) VALUES (?, ?, ?)",
              (req_id, reason, comment))
    conn.commit()
    conn.close()

    return render_template('success.html')

if __name__ == '__main__':
    if not os.path.exists('feedback.db'):
        init_db()
    app.run(debug=True)


