import pytest

from data.users import unknown_account
from pages.login_page import LoginPage

GENERIC_FAILURE = "Email or password is incorrect."


@pytest.mark.smoke
@pytest.mark.tc("TC-AUTH-01")
def test_sign_in_sets_secure_session(page, context, account):
    dashboard = LoginPage(page).open().sign_in(account)

    assert dashboard.is_loaded()

    cookie = next(c for c in context.cookies() if c["name"] == "session")
    assert cookie["secure"] is True
    assert cookie["httpOnly"] is True


@pytest.mark.regression
@pytest.mark.tc("TC-AUTH-02")
def test_wrong_password_does_not_reveal_account(page, context, account):
    login = LoginPage(page).open().attempt_sign_in(account, password="wrong-password")

    # Generic message only. It must not distinguish unknown email from wrong password.
    assert login.error_text() == GENERIC_FAILURE
    assert not [c for c in context.cookies() if c["name"] == "session"]


@pytest.mark.regression
@pytest.mark.tc("TC-AUTH-02")
def test_unknown_email_gets_the_same_response(page):
    login = LoginPage(page).open().attempt_sign_in(unknown_account())

    assert login.error_text() == GENERIC_FAILURE


@pytest.mark.regression
@pytest.mark.tc("TC-AUTH-03")
def test_lockout_after_five_failed_attempts(api, account):
    for _ in range(5):
        assert api.token(account.email, "wrong-password").status_code == 401

    # The sixth attempt is rejected even with the correct password.
    assert api.token(account.email, account.password).status_code == 423

    notices = [row for row in api.outbox(account.id)["data"] if row["kind"] == "lockout_notice"]
    assert len(notices) == 1
