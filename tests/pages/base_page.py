from playwright.sync_api import Page, expect


class BasePage:
    """Waits on conditions, never on time. Pages expose intent, not selectors."""

    path = "/"

    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto(self.path)
        return self

    def tid(self, test_id: str):
        return self.page.get_by_test_id(test_id)

    def fill(self, test_id: str, value: str):
        field = self.tid(test_id)
        expect(field).to_be_visible()
        field.fill(value)

    def click(self, test_id: str):
        button = self.tid(test_id)
        expect(button).to_be_enabled()
        button.click()

    def text_of(self, test_id: str) -> str:
        return self.tid(test_id).inner_text().strip()
