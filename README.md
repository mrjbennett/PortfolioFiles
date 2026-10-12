# Portfolio Sample Files

A small subscription-billing app with three known defects, plus the QA work that finds them: a Postman collection, a PyTest + Playwright suite, a test case library and a device-matrix viewport check. It is the shared codebase behind the sample deliverables on [mikebennettqa.com](https://mikebennettqa.com).

Everything is fictional. There is no client data, no real payment processor and no production configuration anywhere in this repo.

## Run it

You need Python 3.10+ and, for the Postman run, Node 18+.

```bash
git clone https://github.com/mrjbennett/PortfolioFiles
cd PortfolioFiles
python3 -m venv .venv && source .venv/bin/activate
make setup            # Python dependencies and the Chromium that Playwright drives

make test             # build 4.2.1-rc3: 4 tests fail, one or more per seeded defect
make test-fixed       # build 4.2.1: all 20 pass
make newman           # Postman collection on rc3: 2 assertions fail
make newman-fixed     # Postman collection on 4.2.1: all 23 pass
```

To click through the app yourself: `make run`, then open <http://127.0.0.1:5055>. Create an account with `curl -X POST localhost:5055/v1/accounts -H 'content-type: application/json' -d '{"email":"you@example.com","password":"at-least-8-chars"}'`, sign in, and choose a plan. Test cards: `4242 4242 4242 4242` is captured, `4000 0000 0000 0002` is declined.

## The two builds

`BILLING_BUILD=rc3` (the default) is the release candidate. `BILLING_BUILD=fixed` is the same app with the defects corrected. Each defect sits behind a commented `BUILD` check in `app/server.py` and `app/templates/checkout.html`, so the repo doubles as an answer key.

| Defect | What is wrong | How to see it |
| --- | --- | --- |
| BUG-1142 | A replayed payment reaches the processor a second time. The app records one payment; the processor captured two. | `pytest -k double_click` or `-k reconcile`; Postman request "Processor view: charges for the subscription" |
| BUG-1156 | Proration on a 31-day month is calculated as if the period were 30 days: $49.00 instead of $47.42. | `pytest -k 31_day`; Postman request "Upgrade to the pro plan" |
| BUG-1163 | Checkout accepts a card expiry in the past. The `pattern` attribute checks the format, not the date. | `pytest -k past_expiry` |

When a UI test fails, a screenshot, the page source and a Playwright trace are written to `artifacts/<test name>/`. Open a trace with `python -m playwright show-trace <file>.zip`.

## What is in here

| Path | What it is | Sample deliverable |
| --- | --- | --- |
| `app/` | The Flask app, SQLite storage, a stand-in payment processor and a small sandbox API (clock, read-only database views) | Test strategy |
| `postman/` | The collection and a `local` environment | API test collection |
| `tests/` | PyTest + Playwright: page objects, fixtures, API, direct-SQL and viewport checks | Automation framework |
| `docs/test-cases.csv` | The manual test case library in Xray/Zephyr import format | Test case suite |
| `tests/suites/test_layout.py` | Layout check on the Tier 1 and 2 viewports from the device matrix | Device coverage matrix |
| `tests/suites/` (`known_defect` marker) | The tests that fail on rc3, tied to the BUG ids | Defect reports |

Each automated test carries a `tc` marker with the manual case it automates (for example `@pytest.mark.tc("TC-PAY-03")`). `pytest --collect-only -m "tc"` lists them; `-m known_defect` selects the ones that fail on rc3.

## Notes

- **Database.** SQLite, so there is nothing to install. The queries in `tests/suites/test_billing_db.py` are plain SQL and move to PostgreSQL, MySQL or SQL Server by changing the driver and the `db` fixture.
- **Sandbox endpoints.** `/sandbox/*` exists so tests can pin the clock and read state. Set `BILLING_SANDBOX=0` to switch it off. A real engagement would not ship it.
- **Running against a server you started.** Set `BASE_URL`, and `BILLING_DB` if you want the direct-SQL checks.
- **Not automated, on purpose.** TC-AUTH-04 (idle session expiry) and TC-PAY-04 (renewal and dunning) need the time-shifted environment and are written as manual cases only.
