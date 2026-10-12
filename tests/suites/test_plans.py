import pytest

from data.finance import EXPECTED_PRORATION_CENTS


def upgrade_after_twelve_days(api, token, start, later):
    """Subscribe on the standard plan at `start`, then upgrade at `later`."""
    api.set_clock(start)
    subscription_id = api.subscribe(token).json()["id"]
    api.set_clock(later)
    return subscription_id, api.change_plan(token, subscription_id, "pro")


@pytest.mark.regression
@pytest.mark.tc("TC-PLAN-01")
def test_upgrade_mid_cycle_prorates_a_30_day_period(api, token, clock):
    _, response = upgrade_after_twelve_days(api, token, "2026-04-01T00:00:00Z", "2026-04-13T00:00:00Z")

    body = response.json()
    assert response.status_code == 200
    assert body["plan"] == "pro"
    assert body["effective_date"] == "2026-04-13"
    assert body["amount_due"] == EXPECTED_PRORATION_CENTS[30]


@pytest.mark.regression
@pytest.mark.known_defect("BUG-1156")
@pytest.mark.tc("TC-PLAN-03")
def test_upgrade_mid_cycle_prorates_a_31_day_period(api, token, clock):
    _, response = upgrade_after_twelve_days(api, token, "2026-01-01T00:00:00Z", "2026-01-13T00:00:00Z")

    assert response.status_code == 200
    assert response.json()["amount_due"] == EXPECTED_PRORATION_CENTS[31]


@pytest.mark.regression
@pytest.mark.tc("TC-PLAN-02")
def test_downgrade_defers_to_period_end(api, token):
    created = api.subscribe(token, plan="pro").json()
    subscription_id, period_end = created["id"], created["current_period_end"]

    response = api.change_plan(token, subscription_id, "standard")

    body = response.json()
    assert response.status_code == 200
    assert body["plan"] == "pro"  # current tier retained until period end
    assert body["scheduled_plan"] == "standard"
    assert body["effective_date"] == period_end
    assert body["amount_due"] == 0
    assert len(api.invoices(subscription_id)["data"]) == 1  # no immediate charge or refund
