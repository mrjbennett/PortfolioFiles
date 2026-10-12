"""Backend verification: plain SQL against the app database.

SQLite here for zero setup. The queries are standard SQL, so the same checks move to
PostgreSQL, MySQL or SQL Server by changing the driver and the connection fixture.
"""

import uuid

import pytest


def one(db, sql, *params):
    return db.execute(sql, params).fetchone()


@pytest.mark.regression
@pytest.mark.tc("TC-PAY-01")
def test_a_charge_leaves_one_consistent_set_of_rows(api, account, token, db):
    subscription_id = api.subscribe(token).json()["id"]

    assert one(db, "SELECT COUNT(*) FROM subscriptions WHERE account_id = ?", account.id)[0] == 1
    assert tuple(one(
        db,
        "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM invoices WHERE subscription_id = ? AND status = 'paid'",
        subscription_id,
    )) == (1, 9900)
    assert one(db, "SELECT COUNT(*) FROM ledger_entries WHERE subscription_id = ?", subscription_id)[0] == 1

    # Every ledger entry must trace back to a paid invoice for the same amount.
    orphans = one(
        db,
        """SELECT COUNT(*) FROM ledger_entries l
           LEFT JOIN invoices i ON i.subscription_id = l.subscription_id
                               AND i.status = 'paid' AND i.amount = l.amount
           WHERE l.subscription_id = ? AND i.id IS NULL""",
        subscription_id,
    )[0]
    assert orphans == 0


@pytest.mark.regression
@pytest.mark.known_defect("BUG-1142")
@pytest.mark.tc("TC-PAY-03")
def test_processor_charges_reconcile_with_paid_invoices(api, token, db):
    key = str(uuid.uuid4())
    subscription_id = api.subscribe(token, key=key).json()["id"]
    api.subscribe(token, key=key)  # the replay

    invoiced = one(
        db,
        "SELECT COALESCE(SUM(amount), 0) FROM invoices WHERE subscription_id = ? AND status = 'paid'",
        subscription_id,
    )[0]
    assert api.charges(subscription_id)["total"] == invoiced
