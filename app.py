"""
Day 1 Homework: Lakebase-Powered AI Support App.

A small Flask app backed by Lakebase (Databricks-managed Postgres):
- tickets: support tickets with a status
- ticket_messages: messages on a ticket, FK'd to tickets

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os

from flask import Flask, jsonify, render_template, request

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-app")

app = Flask(__name__)

ALLOWED_STATUSES = ("open", "in_progress", "resolved")


def ensure_schema():
    """Create tickets/ticket_messages if they don't exist yet. Idempotent."""
    lakebase.run_write(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'resolved')),
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    lakebase.run_write(
        """
        CREATE TABLE IF NOT EXISTS ticket_messages (
            message_id SERIAL PRIMARY KEY,
            ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
            message_text TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    lakebase.run_write(
        "CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id)"
    )


def seed_if_empty():
    """Insert sample tickets/messages the first time the tables are empty."""
    existing = lakebase.run_query("SELECT ticket_id FROM tickets LIMIT 1")
    if existing:
        return

    tickets = [
        ("Cannot log into dashboard", "open", "grace@acme.com"),
        ("Export button not working", "in_progress", "daniel@acme.com"),
        ("Feature request: dark mode", "resolved", "priya@acme.com"),
    ]
    messages_by_title = {
        "Cannot log into dashboard": [
            ("I get a blank screen after entering my password.", "grace@acme.com"),
            ("Can you share which browser you're using?", "support-agent"),
        ],
        "Export button not working": [
            ("Clicking 'Export CSV' just spins forever.", "daniel@acme.com"),
            ("Reproduced on our end, looking into it now.", "support-agent"),
        ],
        "Feature request: dark mode": [
            ("Would love a dark theme for late-night use.", "priya@acme.com"),
            ("Shipped in the latest release, thanks for the suggestion!", "support-agent"),
        ],
    }

    for title, status, created_by in tickets:
        rows = lakebase.run_write(
            """
            INSERT INTO tickets (title, status, created_by)
            VALUES (%s, %s, %s)
            RETURNING ticket_id
            """,
            (title, status, created_by),
        )
        ticket_id = rows[0]["ticket_id"]
        for message_text, author in messages_by_title[title]:
            lakebase.run_write(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s)
                """,
                (ticket_id, message_text, author),
            )
    logger.info("Seeded %d sample tickets", len(tickets))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_exception(err):
    """Ensure all unhandled errors return JSON, not an HTML error page."""
    logger.exception("Unhandled exception while processing request")
    status_code = getattr(err, "code", 500)
    if not isinstance(status_code, int):
        status_code = 500
    return jsonify({"error": str(err)}), status_code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tickets", methods=["GET"])
def list_tickets():
    """List all tickets, newest first, with a message count per ticket."""
    status_filter = request.args.get("status")
    if status_filter and status_filter not in ALLOWED_STATUSES:
        return jsonify({"error": f"Invalid status filter: {status_filter!r}"}), 400

    sql = """
        SELECT t.ticket_id, t.title, t.status, t.created_by, t.created_at,
               COUNT(m.message_id) AS message_count
        FROM tickets t
        LEFT JOIN ticket_messages m ON m.ticket_id = t.ticket_id
        {where}
        GROUP BY t.ticket_id
        ORDER BY t.created_at DESC
    """.format(where="WHERE t.status = %s" if status_filter else "")
    params = (status_filter,) if status_filter else None
    rows = lakebase.run_query(sql, params)
    return jsonify(rows)


@app.route("/tickets", methods=["POST"])
def create_ticket():
    """Create a new ticket. Body: {title, created_by}."""
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    created_by = (body.get("created_by") or "").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not created_by:
        return jsonify({"error": "created_by is required"}), 400

    rows = lakebase.run_write(
        """
        INSERT INTO tickets (title, created_by)
        VALUES (%s, %s)
        RETURNING ticket_id, title, status, created_by, created_at
        """,
        (title, created_by),
    )
    return jsonify(rows[0]), 201


@app.route("/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id: int):
    """Fetch one ticket plus all of its messages, oldest first."""
    ticket_rows = lakebase.run_query(
        "SELECT ticket_id, title, status, created_by, created_at FROM tickets WHERE ticket_id = %s",
        (ticket_id,),
    )
    if not ticket_rows:
        return jsonify({"error": f"No ticket with id {ticket_id}"}), 404

    messages = lakebase.run_query(
        """
        SELECT message_id, ticket_id, message_text, author, created_at
        FROM ticket_messages
        WHERE ticket_id = %s
        ORDER BY created_at ASC
        """,
        (ticket_id,),
    )
    ticket = ticket_rows[0]
    ticket["messages"] = messages
    return jsonify(ticket)


@app.route("/tickets/<int:ticket_id>", methods=["PATCH"])
def update_ticket_status(ticket_id: int):
    """Update a ticket's status. Body: {status}."""
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").strip()

    if status not in ALLOWED_STATUSES:
        return jsonify(
            {"error": f"status must be one of {ALLOWED_STATUSES}, got {status!r}"}
        ), 400

    rows = lakebase.run_write(
        """
        UPDATE tickets SET status = %s WHERE ticket_id = %s
        RETURNING ticket_id, title, status, created_by, created_at
        """,
        (status, ticket_id),
    )
    if not rows:
        return jsonify({"error": f"No ticket with id {ticket_id}"}), 404
    return jsonify(rows[0])


@app.route("/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id: int):
    """Add a message to a ticket. Body: {message_text, author}."""
    exists = lakebase.run_query("SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,))
    if not exists:
        return jsonify({"error": f"No ticket with id {ticket_id}"}), 404

    body = request.get_json(silent=True) or {}
    message_text = (body.get("message_text") or "").strip()
    author = (body.get("author") or "").strip()

    if not message_text:
        return jsonify({"error": "message_text is required"}), 400
    if not author:
        return jsonify({"error": "author is required"}), 400

    rows = lakebase.run_write(
        """
        INSERT INTO ticket_messages (ticket_id, message_text, author)
        VALUES (%s, %s, %s)
        RETURNING message_id, ticket_id, message_text, author, created_at
        """,
        (ticket_id, message_text, author),
    )
    return jsonify(rows[0]), 201


ensure_schema()
seed_if_empty()


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", 8000))
    app.run(debug=True, host=host, port=port)
