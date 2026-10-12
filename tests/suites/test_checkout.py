import pytest

from pages.login_page import LoginPage

VALID_CARD = ("4242 4242 4242 4242", "12/30")
DECLINE_CARD = ("4000 0000 0000 0002", "12/30")


def open_checkout(page, account):
    return LoginPage(page).open().sign_in(account).choose_plan()


@pytest.mark.smoke
@pytest.mark.tc("TC-PAY-01")
def test_first_charge_with_a_valid_card(page, api, account):
    checkout = open_checkout(page, account)

    assert checkout.pay(*VALID_CARD) == "Subscription active"

    subscription_id = checkout.subscription_id()
    assert api.subscription_rows(account.id)["data"][0]["status"] == "active"
    assert api.charges(subscription_id)["count"] == 1
    assert api.ledger(subscription_id)["count"] == 1  # ledger event delivered exactly once
    receipts = [row for row in api.outbox(account.id)["data"] if row["kind"] == "receipt"]
    assert len(receipts) == 1


@pytest.mark.regression
@pytest.mark.tc("TC-PAY-02")
def test_declined_card_leaves_no_partial_state(page, api, account):
    checkout = open_checkout(page, account)

    assert checkout.pay(*DECLINE_CARD) == "Card declined: insufficient funds."

    assert api.subscription_rows(account.id)["count"] == 0
    assert api.outbox(account.id)["count"] == 0


@pytest.mark.regression
@pytest.mark.known_defect("BUG-1142")
@pytest.mark.tc("TC-PAY-03")
def test_double_click_on_confirm_charges_once(page, api, account):
    checkout = open_checkout(page, account)
    checkout.fill_card(*VALID_CARD)

    checkout.double_click_confirm()
    checkout.result_text()
    checkout.wait_for_requests_to_settle()

    assert api.charges(checkout.subscription_id())["count"] == 1


@pytest.mark.regression
@pytest.mark.known_defect("BUG-1163")
@pytest.mark.tc("TC-PAY-05")
def test_past_expiry_is_rejected_before_anything_is_sent(page, account):
    checkout = open_checkout(page, account)
    checkout.fill_card("4242 4242 4242 4242", "01/22").confirm()

    checkout.expect_expiry_error("Card expiry is in the past.")
    assert checkout.submissions == []
