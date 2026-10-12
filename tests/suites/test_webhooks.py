import uuid

import pytest


@pytest.mark.regression
@pytest.mark.tc("TC-HOOK-01")
def test_duplicate_event_is_acknowledged_not_reprocessed(api, token):
    subscription_id = api.subscribe(token).json()["id"]
    event = api.events(subscription_id)["data"][0]
    payload = {k: event[k] for k in ("id", "type", "subscription_id", "amount")}

    first = api.deliver_event(payload)
    second = api.deliver_event(payload)

    assert first.json()["status"] == "duplicate"  # the app already delivered it on payment
    assert second.json()["status"] == "duplicate"
    assert api.ledger(subscription_id)["count"] == 1


@pytest.mark.regression
@pytest.mark.tc("TC-HOOK-02")
def test_malformed_event_is_rejected_without_a_partial_write(api, token):
    subscription_id = api.subscribe(token).json()["id"]
    event_id = f"evt_bad_{uuid.uuid4().hex[:8]}"

    response = api.deliver_event({"id": event_id, "type": "payment.succeeded", "subscription_id": subscription_id})

    assert response.status_code == 400  # a 4xx, so the sender does not retry
    assert api.ledger(subscription_id)["count"] == 1  # nothing written beyond the original payment
    log = api.webhook_log(event_id)["data"]
    assert [row["outcome"] for row in log] == ["rejected"]
