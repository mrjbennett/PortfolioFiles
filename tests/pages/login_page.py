import re

from playwright.sync_api import expect

from .base_page import BasePage
from .dashboard_page import DashboardPage


class LoginPage(BasePage):
    path = "/"

    def attempt_sign_in(self, account, password=None):
        """Submit credentials and stay on this page (for failure cases)."""
        self.fill("email", account.email)
        self.fill("password", password if password is not None else account.password)
        self.click("sign-in")
        return self

    def sign_in(self, account) -> DashboardPage:
        self.attempt_sign_in(account)
        expect(self.page).to_have_url(re.compile(r"/dashboard$"))
        return DashboardPage(self.page)

    def error_text(self) -> str:
        expect(self.tid("error")).not_to_be_empty()
        return self.text_of("error")
