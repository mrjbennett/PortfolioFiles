import re

from playwright.sync_api import expect

from .base_page import BasePage


class DashboardPage(BasePage):
    path = "/dashboard"

    def is_loaded(self) -> bool:
        expect(self.tid("welcome")).to_be_visible()
        return True

    def plan_text(self) -> str:
        return self.text_of("plan")

    def choose_plan(self):
        from .checkout_page import CheckoutPage

        self.click("choose-plan")
        expect(self.page).to_have_url(re.compile(r"/checkout$"))
        return CheckoutPage(self.page)
