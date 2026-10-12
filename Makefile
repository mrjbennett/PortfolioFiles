PY ?= python3
PORT ?= 5055

.PHONY: setup run run-fixed test test-fixed newman newman-fixed

setup:            ## one-time: Python deps + the Chromium Playwright drives
	$(PY) -m pip install -r requirements.txt
	$(PY) -m playwright install chromium

run:              ## serve the rc3 build (3 seeded defects) on :$(PORT)
	PORT=$(PORT) BILLING_BUILD=rc3 $(PY) -m app.server

run-fixed:        ## serve the fixed build on :$(PORT)
	PORT=$(PORT) BILLING_BUILD=fixed $(PY) -m app.server

test:             ## PyTest + Playwright against rc3: the known-defect tests fail by design
	BILLING_BUILD=rc3 $(PY) -m pytest

test-fixed:       ## PyTest + Playwright against the fixed build: everything passes
	BILLING_BUILD=fixed $(PY) -m pytest

newman:           ## Postman collection against rc3: two assertions fail by design
	bash scripts/newman.sh rc3

newman-fixed:     ## Postman collection against the fixed build: everything passes
	bash scripts/newman.sh fixed
