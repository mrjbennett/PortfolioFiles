"""Demo subscription billing app.

Two builds, selected with BILLING_BUILD:

  rc3    (default) the release candidate, with three seeded defects:
           BUG-1142  duplicate charge when a payment is submitted twice
           BUG-1156  proration on a 31-day month uses a 30-day period
           BUG-1163  checkout accepts a card expiry in the past
  fixed  the same app with all three defects corrected

Every seeded defect sits behind an explicit `BUILD` check and a comment, so the repo
doubles as an answer key. The test suites are written to fail on rc3 and pass on fixed.
"""

import json
import os
import re
import secrets
import threading
import uuid
from datetime import date, datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import billing, db, processor

BUILD = os.environ.get("BILLING_BUILD", "rc3")
VERSION = "4.2.1" if BUILD == "fixed" else "4.2.1-rc3"
SANDBOX = os.environ.get("BILLING_SANDBOX", "1") == "1"
LOCKOUT_THRESHOLD = 5
WRITE_LOCK = threading.RLock()

app = Flask(__name__)
db.init()


# --------------------------------------------------------------------------- helpers


def err(status, code, message):
    return jsonify({"error": code, "message": message}), status


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def stamp():
    return billing.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def account_from_request(conn):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        row = conn.execute(
            "SELECT account_id FROM tokens WHERE token = ?", (header[7:],)
        ).fetchone()
        return row["account_id"] if row else None
    return session_account(conn)


def session_account(conn):
    sid = request.cookies.get("session")
    if not sid:
        return None
    row = conn.execute("SELECT account_id FROM sessions WHERE id = ?", (sid,)).fetchone()
    return row["account_id"] if row else None


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        with db.tx() as conn:
            account_id = account_from_request(conn)
        if not account_id:
            return err(401, "unauthorized", "Authentication required.")
        g.account_id = account_id
        return view(*args, **kwargs)

    return wrapper


def check_credentials(conn, email, password):
    """Return ("ok" | "invalid" | "locked", account_id)."""
    row = conn.execute(
        "SELECT * FROM accounts WHERE email = ?", ((email or "").strip().lower(),)
    ).fetchone()
    if row is None:
        return "invalid", None
    if row["locked"]:
        return "locked", None
    if check_password_hash(row["password_hash"], password or ""):
        conn.execute("UPDATE accounts SET failed_logins = 0 WHERE id = ?", (row["id"],))
        return "ok", row["id"]
    failed = row["failed_logins"] + 1
    locked = 1 if failed >= LOCKOUT_THRESHOLD else 0
    conn.execute(
        "UPDATE accounts SET failed_logins = ?, locked = ? WHERE id = ?",
        (failed, locked, row["id"]),
    )
    if locked:
        conn.execute(
            "INSERT INTO outbox (account_id, kind, created_at) VALUES (?, 'lockout_notice', ?)",
            (row["id"], stamp()),
        )
    return "invalid", None


def subscription_json(row):
    return {
        "id": row["id"],
        "status": row["status"],
        "plan": row["plan"],
        "current_period_end": row["current_period_end"],
        "customer_id": row["account_id"],
    }


def record_payment(conn, subscription_id, amount):
    """Write the payment event and deliver it to the ledger consumer."""
    event_id = new_id("evt")
    conn.execute(
        "INSERT INTO events (id, type, subscription_id, amount, created_at) VALUES (?, 'payment.succeeded', ?, ?, ?)",
        (event_id, subscription_id, amount, stamp()),
    )
    conn.execute(
        "INSERT INTO ledger_entries (event_id, subscription_id, amount, created_at) VALUES (?, ?, ?, ?)",
        (event_id, subscription_id, amount, stamp()),
    )
    conn.execute(
        "INSERT INTO webhook_log (event_id, outcome, reason, created_at) VALUES (?, 'processed', NULL, ?)",
        (event_id, stamp()),
    )


# ------------------------------------------------------------------------------- API


@app.get("/health")
def health():
    return jsonify({"status": "ok", "build": VERSION})


@app.post("/v1/accounts")
def create_account():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return err(422, "invalid_email", "A valid email address is required.")
    if len(password) < 8:
        return err(422, "weak_password", "Password must be at least 8 characters.")
    account_id = new_id("cus")
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
            return err(409, "email_taken", "An account with this email already exists.")
        conn.execute(
            "INSERT INTO accounts (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (account_id, email, generate_password_hash(password, method="pbkdf2:sha256:20000"), stamp()),
        )
    return jsonify({"id": account_id, "email": email}), 201


@app.post("/v1/auth/token")
def issue_token():
    body = request.get_json(silent=True) or {}
    with db.tx() as conn:
        status, account_id = check_credentials(conn, body.get("email"), body.get("password"))
        if status == "ok":
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO tokens (token, account_id) VALUES (?, ?)", (token, account_id))
            return jsonify({"access_token": token, "token_type": "Bearer", "customer_id": account_id})
    if status == "locked":
        return err(423, "account_locked", "Account locked. Check your email for next steps.")
    return err(401, "invalid_credentials", "Email or password is incorrect.")


@app.post("/v1/subscriptions")
@require_auth
def create_subscription():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return err(400, "invalid_json", "Request body must be a JSON object.")
    plan, card = body.get("plan"), body.get("card")
    if plan not in billing.PLANS:
        return err(422, "invalid_plan", "Plan must be one of: " + ", ".join(billing.PLANS) + ".")
    if not isinstance(card, dict) or not str(card.get("number", "")).isdigit():
        return err(422, "invalid_card", "A card number is required.")
    exp = card.get("exp") or ""
    if not re.fullmatch(r"(0[1-9]|1[0-2])/\d{2}", exp):
        return err(422, "invalid_card_expiry", "Card expiry must be MM/YY.")
    key = request.headers.get("Idempotency-Key")

    with WRITE_LOCK, db.tx() as conn:
        existing = conn.execute(
            "SELECT * FROM subscriptions WHERE account_id = ?", (g.account_id,)
        ).fetchone()
        seen = None
        if key:
            seen = conn.execute(
                "SELECT response FROM idempotency WHERE account_id = ? AND key = ?",
                (g.account_id, key),
            ).fetchone()

        if seen:
            stored = json.loads(seen["response"])
            if BUILD != "fixed":
                # Seeded defect BUG-1142: the key is recognised and the original response
                # is returned, but the processor is called a second time first. The
                # charge is captured and nothing in the app records it.
                try:
                    processor.charge(card["number"], exp, billing.PLANS[plan], existing["id"])
                except processor.Declined:
                    pass
                return jsonify(stored), 200
            resp = jsonify(stored)
            resp.headers["Idempotent-Replayed"] = "true"
            return resp, 200

        if existing:
            return err(409, "already_subscribed", "This account already has a subscription.")

        sub_id = new_id("sub")
        amount = billing.PLANS[plan]
        try:
            processor.charge(card["number"], exp, amount, sub_id)
        except processor.Declined as declined:
            if declined.code == "card_declined":
                return err(402, "card_declined", "Card declined: " + declined.reason.replace("_", " ") + ".")
            return err(402, "payment_failed", "Your payment could not be processed.")

        start = billing.now().date()
        end = billing.add_month(start)
        conn.execute(
            "INSERT INTO subscriptions (id, account_id, plan, status, period_start, current_period_end) VALUES (?, ?, ?, 'active', ?, ?)",
            (sub_id, g.account_id, plan, start.isoformat(), end.isoformat()),
        )
        conn.execute(
            "INSERT INTO invoices (id, account_id, subscription_id, kind, amount, status, created_at) VALUES (?, ?, ?, 'subscription', ?, 'paid', ?)",
            (new_id("inv"), g.account_id, sub_id, amount, stamp()),
        )
        record_payment(conn, sub_id, amount)
        conn.execute(
            "INSERT INTO outbox (account_id, kind, created_at) VALUES (?, 'receipt', ?)",
            (g.account_id, stamp()),
        )
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        payload = subscription_json(row)
        if key:
            conn.execute(
                "INSERT INTO idempotency (account_id, key, response) VALUES (?, ?, ?)",
                (g.account_id, key, json.dumps(payload)),
            )
    resp = jsonify(payload)
    resp.headers["Location"] = f"/v1/subscriptions/{sub_id}"
    return resp, 201


@app.get("/v1/subscriptions/<sub_id>")
@require_auth
def get_subscription(sub_id):
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ? AND account_id = ?", (sub_id, g.account_id)
        ).fetchone()
    if row is None:
        return err(404, "not_found", "No such subscription.")
    return jsonify(subscription_json(row))


@app.patch("/v1/subscriptions/<sub_id>/plan")
@require_auth
def change_plan(sub_id):
    body = request.get_json(silent=True) or {}
    new_plan = body.get("plan")
    if new_plan not in billing.PLANS:
        return err(422, "invalid_plan", "Plan must be one of: " + ", ".join(billing.PLANS) + ".")
    with WRITE_LOCK, db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ? AND account_id = ?", (sub_id, g.account_id)
        ).fetchone()
        if row is None:
            return err(404, "not_found", "No such subscription.")
        if new_plan == row["plan"]:
            return err(409, "same_plan", "Subscription is already on this plan.")

        today = billing.now().date()
        difference = billing.PLANS[new_plan] - billing.PLANS[row["plan"]]
        if difference < 0:
            conn.execute("UPDATE subscriptions SET scheduled_plan = ? WHERE id = ?", (new_plan, sub_id))
            return jsonify({
                "id": sub_id, "plan": row["plan"], "scheduled_plan": new_plan,
                "amount_due": 0, "effective_date": row["current_period_end"],
            })

        start = date.fromisoformat(row["period_start"])
        end = date.fromisoformat(row["current_period_end"])
        period_days = billing.days_between(start, end)
        remaining = billing.days_between(today, end)
        if BUILD != "fixed":
            # Seeded defect BUG-1156: the period length is hardcoded to 30 days, so every
            # upgrade in a 31-day month is overcharged.
            period_days = 30
        amount = billing.prorate(difference, remaining, period_days)

        conn.execute(
            "UPDATE subscriptions SET plan = ?, scheduled_plan = NULL WHERE id = ?", (new_plan, sub_id)
        )
        conn.execute(
            "INSERT INTO invoices (id, account_id, subscription_id, kind, amount, status, created_at) VALUES (?, ?, ?, 'proration', ?, 'open', ?)",
            (new_id("inv"), g.account_id, sub_id, amount, stamp()),
        )
    return jsonify({
        "id": sub_id, "plan": new_plan, "scheduled_plan": None,
        "amount_due": amount, "effective_date": today.isoformat(),
    })


@app.get("/v1/invoices")
@require_auth
def list_invoices():
    status = request.args.get("status")
    query = "SELECT * FROM invoices WHERE account_id = ?"
    params = [g.account_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    with db.tx() as conn:
        rows = conn.execute(query + " ORDER BY created_at, id", params).fetchall()
    return jsonify({"data": [
        {"id": r["id"], "subscription_id": r["subscription_id"], "customer_id": r["account_id"],
         "kind": r["kind"], "amount": r["amount"], "status": r["status"]}
        for r in rows
    ]})


@app.post("/v1/webhooks/events")
def inbound_event():
    """Ledger consumer. Idempotent on the event id; rejects malformed events without writing."""
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    event_id = body.get("id")
    missing = [f for f in ("id", "type", "subscription_id", "amount") if f not in body]
    with db.tx() as conn:
        if missing:
            reason = "missing required field(s): " + ", ".join(missing)
            conn.execute(
                "INSERT INTO webhook_log (event_id, outcome, reason, created_at) VALUES (?, 'rejected', ?, ?)",
                (event_id, reason, stamp()),
            )
            return err(400, "invalid_event", "Event rejected: " + reason + ".")
        if conn.execute("SELECT 1 FROM ledger_entries WHERE event_id = ?", (event_id,)).fetchone():
            conn.execute(
                "INSERT INTO webhook_log (event_id, outcome, reason, created_at) VALUES (?, 'duplicate', NULL, ?)",
                (event_id, stamp()),
            )
            return jsonify({"status": "duplicate", "event_id": event_id})
        conn.execute(
            "INSERT INTO ledger_entries (event_id, subscription_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (event_id, body["subscription_id"], body["amount"], stamp()),
        )
        conn.execute(
            "INSERT INTO webhook_log (event_id, outcome, reason, created_at) VALUES (?, 'processed', NULL, ?)",
            (event_id, stamp()),
        )
    return jsonify({"status": "processed", "event_id": event_id})


# --------------------------------------------------------------------------- sandbox
# Read-only views and controls for tests. Never enabled in a production deployment.

if SANDBOX:

    def rows(conn, query, params=()):
        return [dict(r) for r in conn.execute(query, params).fetchall()]

    @app.post("/sandbox/reset")
    def sandbox_reset():
        db.reset()
        processor.reset()
        billing.set_clock(None)
        return jsonify({"status": "reset"})

    @app.route("/sandbox/clock", methods=["GET", "POST"])
    def sandbox_clock():
        if request.method == "POST":
            value = (request.get_json(silent=True) or {}).get("now")
            if value is None:
                billing.set_clock(None)
            else:
                billing.set_clock(
                    datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
                )
        return jsonify({"now": stamp(), "overridden": billing.get_clock_override() is not None})

    @app.get("/sandbox/processor/charges")
    def sandbox_charges():
        data = processor.charges(request.args.get("subscription_id"))
        return jsonify({"data": data, "count": len(data), "total": sum(c["amount"] for c in data)})

    @app.get("/sandbox/db/invoices")
    def sandbox_invoices():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM invoices WHERE subscription_id = ? ORDER BY created_at, id",
                        (request.args.get("subscription_id"),))
        paid = [r for r in data if r["status"] == "paid"]
        return jsonify({"data": data, "paid_count": len(paid), "paid_total": sum(r["amount"] for r in paid)})

    @app.get("/sandbox/db/subscriptions")
    def sandbox_subscriptions():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM subscriptions WHERE account_id = ?",
                        (request.args.get("account_id"),))
        return jsonify({"data": data, "count": len(data)})

    @app.get("/sandbox/events")
    def sandbox_events():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM events WHERE subscription_id = ? ORDER BY created_at",
                        (request.args.get("subscription_id"),))
        return jsonify({"data": data, "count": len(data)})

    @app.get("/sandbox/ledger")
    def sandbox_ledger():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM ledger_entries WHERE subscription_id = ? ORDER BY id",
                        (request.args.get("subscription_id"),))
        return jsonify({"data": data, "count": len(data)})

    @app.get("/sandbox/webhook-log")
    def sandbox_webhook_log():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM webhook_log WHERE event_id IS ? ORDER BY id",
                        (request.args.get("event_id"),))
        return jsonify({"data": data, "count": len(data)})

    @app.get("/sandbox/outbox")
    def sandbox_outbox():
        with db.tx() as conn:
            data = rows(conn, "SELECT * FROM outbox WHERE account_id = ? ORDER BY id",
                        (request.args.get("account_id"),))
        return jsonify({"data": data, "count": len(data)})


# ---------------------------------------------------------------------------- pages


@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    with db.tx() as conn:
        status, account_id = check_credentials(conn, body.get("email"), body.get("password"))
        if status == "ok":
            sid = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO sessions (id, account_id) VALUES (?, ?)", (sid, account_id))
            resp = jsonify({"redirect": "/dashboard"})
            resp.set_cookie("session", sid, httponly=True, secure=True, samesite="Lax", path="/")
            return resp
    if status == "locked":
        return err(423, "account_locked", "Account locked. Check your email for next steps.")
    return err(401, "invalid_credentials", "Email or password is incorrect.")


@app.get("/")
def index():
    return render_template("login.html", version=VERSION)


@app.get("/dashboard")
def dashboard():
    with db.tx() as conn:
        account_id = session_account(conn)
        if not account_id:
            return redirect("/")
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        sub = conn.execute("SELECT * FROM subscriptions WHERE account_id = ?", (account_id,)).fetchone()
    return render_template("dashboard.html", version=VERSION, email=account["email"], sub=sub)


@app.get("/checkout")
def checkout():
    with db.tx() as conn:
        if not session_account(conn):
            return redirect("/")
    return render_template(
        "checkout.html", version=VERSION, fixed=(BUILD == "fixed"),
        plans={name: f"${cents / 100:,.2f}" for name, cents in billing.PLANS.items()},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5055")), threaded=True)
