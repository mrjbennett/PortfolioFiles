from playwright.sync_api import expect

from .base_page import BasePage


class CheckoutPage(BasePage):
    path = "/checkout"

    def __init__(self, page):
        super().__init__(page)
        self.submissions = []
        page.on(
            "request",
            lambda request: self.submissions.append(request)
            if request.method == "POST" and request.url.endswith("/v1/subscriptions")
            else None,
        )

    def fill_card(self, number: str, exp: str, plan: str = "standard"):
        self.tid("plan").select_option(plan)
        self.fill("card-number", number)
        self.fill("card-expiry", exp)
        return self

    def confirm(self):
        self.click("confirm")
        return self

    def double_click_confirm(self):
        """Two clicks inside the window where the first response has not returned."""
        button = self.tid("confirm")
        expect(button).to_be_enabled()
        button.dblclick()
        return self

    def pay(self, number: str, exp: str, plan: str = "standard"):
        self.fill_card(number, exp, plan).confirm()
        return self.result_text()

    def result_text(self) -> str:
        expect(self.tid("result")).not_to_be_empty()
        return self.text_of("result")

    def subscription_id(self) -> str:
        return self.tid("result").get_attribute("data-subscription-id")

    def wait_for_requests_to_settle(self):
        self.page.wait_for_load_state("networkidle")

    def expect_expiry_error(self, message: str):
        expect(self.tid("expiry-error")).to_have_text(message, timeout=2000)

    def has_horizontal_scroll(self) -> bool:
        return self.page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")

    def confirm_is_unobstructed(self) -> bool:
        """The button sits inside the viewport and is the element a tap would actually hit."""
        return self.page.evaluate(
            """() => {
              const button = document.querySelector('[data-testid=confirm]');
              const box = button.getBoundingClientRect();
              const x = box.left + box.width / 2, y = box.top + box.height / 2;
              const inside = box.top >= 0 && box.bottom <= window.innerHeight
                          && box.left >= 0 && box.right <= window.innerWidth;
              const hit = document.elementFromPoint(x, y);
              return inside && (hit === button || button.contains(hit));
            }"""
        )
