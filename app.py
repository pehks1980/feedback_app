from datetime import datetime, timedelta, timezone
from flask import Flask, request, render_template, redirect, url_for
import logging
import sqlite3
import uuid
import os
import sys

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("feedback_app")

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

def short_id(value):
    return value[:8] if value else "-"


def is_admin_request(admin_req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role FROM requests WHERE id=?", (admin_req_id,))
    admin_row = c.fetchone()
    conn.close()
    return bool(admin_row and admin_row[0] == "admin")


def create_feedback_link(employer_id, company_name):
    req_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
              (req_id, employer_id, company_name, "user", expires_at))
    conn.commit()
    conn.close()

    return f"http://{DOMAIN}/feedback/{req_id}"


def init_db():
    """Initialize database and create admin user if needed"""
    logger.info("db_init_start db_path=%s", DB_PATH)
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
        logger.info("admin_link_created admin_id=%s link=%s", short_id(admin_id), f"http://{DOMAIN}/feedback/{admin_id}")

        # Save admin link to file in data directory
        with open(ADMIN_LINK_PATH, 'w') as f:
            f.write(link)

    conn.commit()
    conn.close()


@app.route('/admin/<admin_req_id>', methods=['POST'])
@limiter.limit("10 per minute")
def admin(admin_req_id):
    if request.method == 'POST':
        employer_id = request.form['employer_id']
        company_name = request.form['company_name']

        if not is_admin_request(admin_req_id):
            logger.info("feedback_link_rejected source=html admin_id=%s reason=invalid_admin", short_id(admin_req_id))
            return "Invalid admin link", 403

        link = create_feedback_link(employer_id, company_name)
        logger.info(
            "feedback_link_created source=html admin_id=%s company=%r employer_id=%r link=%s",
            short_id(admin_req_id),
            company_name,
            employer_id,
            link,
        )
        return render_template(f"{RU}fblink.html", link=link)

    return render_template(f'{RU}success.html')


@app.route('/api/admin/companies', methods=['POST'])
@limiter.limit("10 per minute")
def api_admin_companies():
    data = request.get_json(silent=True) or {}

    admin_id = data.get('admin_id', '').strip()
    employer_id = data.get('employer_id', '').strip()
    company_name = data.get('company_name', '').strip()

    if not admin_id:
        logger.info("api_company_create_rejected reason=missing_admin_id")
        return "Error: Admin ID is missing", 400

    if not employer_id:
        logger.info("api_company_create_rejected admin_id=%s reason=missing_employer_id", short_id(admin_id))
        return "Error: Employer ID is missing", 400

    if not company_name:
        logger.info("api_company_create_rejected admin_id=%s reason=missing_company_name", short_id(admin_id))
        return "Error: Company name is missing", 400

    if not is_admin_request(admin_id):
        logger.info("api_company_create_rejected admin_id=%s reason=invalid_admin", short_id(admin_id))
        return "Invalid admin link", 403

    link = create_feedback_link(employer_id, company_name)
    logger.info(
        "feedback_link_created source=api admin_id=%s company=%r employer_id=%r link=%s",
        short_id(admin_id),
        company_name,
        employer_id,
        link,
    )
    return link


@app.route('/feedback/<req_id>')
@limiter.limit("60 per minute")
def landing(req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT company_name, role, expires_at FROM requests WHERE id=?", (req_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        logger.info("feedback_link_rejected request_id=%s reason=not_found", short_id(req_id))
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
            logger.info("feedback_link_rejected request_id=%s company=%r reason=expired", short_id(req_id), company_name)
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
        logger.info("admin_panel_opened admin_id=%s rows=%s", short_id(req_id), len(rows))
        return render_template('admin.html', rows=rows, admin_req_id=req_id)

    conn.close()
    logger.info("feedback_link_opened request_id=%s company=%r", short_id(req_id), company_name)
    return render_template(f'{RU}landing.html', req_id=req_id, company_name=company_name, expires_at=expires_pretty)


@app.route('/admin/companies/<admin_req_id>')
@limiter.limit("30 per minute")
def admin_companies(admin_req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT role FROM requests WHERE id=?", (admin_req_id,))
    admin_row = c.fetchone()

    if not admin_row or admin_row[0] != "admin":
        conn.close()
        logger.info("admin_companies_rejected admin_id=%s reason=invalid_admin", short_id(admin_req_id))
        return "Invalid admin link", 403

    c.execute('''
        SELECT company_name, employer_id, id, expires_at
        FROM requests
        WHERE role = 'user'
        ORDER BY company_name COLLATE NOCASE ASC, employer_id COLLATE NOCASE ASC
    ''')
    company_rows = c.fetchall()
    conn.close()
    logger.info("admin_companies_opened admin_id=%s companies=%s", short_id(admin_req_id), len(company_rows))

    companies = [
        {
            "company_name": row[0],
            "employer_id": row[1],
            "link": f"http://{DOMAIN}/feedback/{row[2]}",
            "expires_at": row[3],
        }
        for row in company_rows
    ]

    return render_template(
        'admin_companies.html',
        companies=companies,
        admin_req_id=admin_req_id,
    )


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
        logger.info("feedback_submit_rejected reason=missing_request_id")
        return "Error: Request ID is missing", 400

    if not reason:
        logger.info("feedback_submit_rejected request_id=%s reason=missing_reason", short_id(req_id))
        return "Error: Please select a reason", 400

    valid_reasons = ['experience', 'better_candidate', 'salary', 'stack', 'other']
    if reason not in valid_reasons:
        logger.info("feedback_submit_rejected request_id=%s reason=invalid_reason submitted_reason=%r", short_id(req_id), reason)
        return "Error: Invalid reason selected", 400

    if len(comment) > 1000:
        logger.info("feedback_submit_rejected request_id=%s reason=comment_too_long length=%s", short_id(req_id), len(comment))
        return "Error: Comment is too long (max 1000 characters)", 400

    if reason == 'other' and not comment:
        logger.info("feedback_submit_rejected request_id=%s reason=missing_other_comment", short_id(req_id))
        return "Error: Please provide details when selecting 'Other'", 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO responses (request_id, reason, comment) VALUES (?, ?, ?)",
              (req_id, reason, comment))
    conn.commit()
    conn.close()

    logger.info("feedback_submitted request_id=%s reason=%s has_comment=%s", short_id(req_id), reason, bool(comment))
    return render_template(f'{RU}success.html')

@app.route('/debug/env')
@limiter.limit("10 per minute")
def debug_env():
    return {
        'DOMAIN': DOMAIN,
        'FLASK_DEBUG': FLASK_DEBUG,
        'RU': RU
    }

logger.info("app_start db_path=%s domain=%s debug=%s", DB_PATH, DOMAIN, FLASK_DEBUG)
if os.path.exists(ADMIN_LINK_PATH):
    logger.info("admin_link_loaded path=%s", ADMIN_LINK_PATH)
if not os.path.exists(DB_PATH):
    init_db()

#app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)
