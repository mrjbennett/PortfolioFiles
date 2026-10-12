"""Thin client for the billing API and its sandbox views."""

import requests

DEFAULT_CARD = {"number": "4242424242424242", "exp": "12/30"}


class BillingApi:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.http = requests.Session()

    def request(self, method, path, token=None, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.http.request(method, self.base_url + path, headers=headers, timeout=10, **kwargs)

    # --- product API
    def create_account(self, email, password):
        return self.request("POST", "/v1/accounts", json={"email": email, "password": password})

    def token(self, email, password):
        return self.request("POST", "/v1/auth/token", json={"email": email, "password": password})

    def subscribe(self, token, plan="standard", card=None, key=None):
        headers = {"Idempotency-Key": key} if key else {}
        return self.request(
            "POST", "/v1/subscriptions", token=token, headers=headers,
            json={"plan": plan, "card": card or DEFAULT_CARD},
        )

    def change_plan(self, token, subscription_id, plan):
        return self.request("PATCH", f"/v1/subscriptions/{subscription_id}/plan", token=token, json={"plan": plan})

    def deliver_event(self, payload):
        return self.request("POST", "/v1/webhooks/events", json=payload)

    # --- sandbox views (read-only except the clock)
    def set_clock(self, iso):
        return self.request("POST", "/sandbox/clock", json={"now": iso}).json()

    def charges(self, subscription_id):
        return self.request("GET", "/sandbox/processor/charges", params={"subscription_id": subscription_id}).json()

    def invoices(self, subscription_id):
        return self.request("GET", "/sandbox/db/invoices", params={"subscription_id": subscription_id}).json()

    def subscription_rows(self, account_id):
        return self.request("GET", "/sandbox/db/subscriptions", params={"account_id": account_id}).json()

    def ledger(self, subscription_id):
        return self.request("GET", "/sandbox/ledger", params={"subscription_id": subscription_id}).json()

    def events(self, subscription_id):
        return self.request("GET", "/sandbox/events", params={"subscription_id": subscription_id}).json()

    def outbox(self, account_id):
        return self.request("GET", "/sandbox/outbox", params={"account_id": account_id}).json()

    def webhook_log(self, event_id):
        return self.request("GET", "/sandbox/webhook-log", params={"event_id": event_id}).json()
