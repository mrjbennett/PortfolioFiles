"""Fixtures: a throwaway server per session, generated accounts, a browser with
screenshot, page source and trace captured on failure.

Point the suite at a server you already run with BASE_URL (and BILLING_DB if you want
the direct-SQL checks); otherwise it starts the app itself on a free port.
"""

import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests
from playwright.sync_api import sync_playwright

from api import BillingApi
from data.users import new_account

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
SEEN = {"build": None}


@dataclass
class Server:
    base_url: str
    db_path: str | None


# ------------------------------------------------------------------ server and API


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    external = os.environ.get("BASE_URL")
    if external:
        yield Server(external.rstrip("/"), os.environ.get("BILLING_DB"))
        return

    port = _free_port()
    db_path = str(Path(tempfile.mkdtemp()) / "billing.db")
    env = {
        **os.environ,
        "PORT": str(port),
        "BILLING_DB": db_path,
        "BILLING_BUILD": os.environ.get("BILLING_BUILD", "rc3"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.server"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while True:
        try:
            if requests.get(base_url + "/health", timeout=1).ok:
                break
        except requests.ConnectionError:
            pass
        if time.monotonic() > deadline:
            process.terminate()
            raise RuntimeError("billing app did not start")
        time.sleep(0.2)
    yield Server(base_url, db_path)
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(scope="session")
def base_url(server):
    return server.base_url


@pytest.fixture(scope="session")
def api(base_url):
    client = BillingApi(base_url)
    SEEN["build"] = client.request("GET", "/health").json()["build"]
    client.set_clock(None)
    return client


@pytest.fixture(scope="session")
def build(api):
    return SEEN["build"]


@pytest.fixture
def account(api):
    return new_account(api)


@pytest.fixture
def token(api, account):
    response = api.token(account.email, account.password)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def clock(api):
    """Set the sandbox clock; always put it back."""
    yield api.set_clock
    api.set_clock(None)


@pytest.fixture
def db(server):
    """Read-only connection to the app database, for direct SQL checks."""
    if not server.db_path:
        pytest.skip("set BILLING_DB to run direct-SQL checks against an external server")
    conn = sqlite3.connect(server.db_path, timeout=10)
    conn.execute("PRAGMA query_only = ON")
    yield conn
    conn.close()


# ------------------------------------------------------------------------ browser


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=os.environ.get("HEADED") != "1")
        yield instance
        instance.close()


@pytest.fixture
def context_factory(browser, base_url, request):
    """Create browser contexts. On failure each one leaves a screenshot, the page
    source and a trace in artifacts/<test>/, so a failed run is already evidence."""
    contexts = []

    def make(**options):
        context = browser.new_context(base_url=base_url, **options)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        contexts.append(context)
        return context

    yield make

    failed = getattr(request.node, "rep_call", None) and request.node.rep_call.failed
    folder = ARTIFACTS / re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
    for index, context in enumerate(contexts):
        if failed:
            folder.mkdir(parents=True, exist_ok=True)
            for number, page in enumerate(context.pages):
                page.screenshot(path=str(folder / f"screenshot-{index}-{number}.png"), full_page=True)
                (folder / f"page-{index}-{number}.html").write_text(page.content())
            context.tracing.stop(path=str(folder / f"trace-{index}.zip"))
        else:
            context.tracing.stop()
        context.close()


@pytest.fixture
def context(context_factory):
    return context_factory()


@pytest.fixture
def page(context):
    return context.new_page()


# ---------------------------------------------------------------- reporting hooks


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)
    marker = item.get_closest_marker("known_defect")
    report.known_defect = marker.args[0] if marker else None


def pytest_terminal_summary(terminalreporter):
    failed = [r for r in terminalreporter.stats.get("failed", []) if getattr(r, "known_defect", None)]
    if not failed:
        return
    terminalreporter.section(f"Known defects reproduced on build {SEEN['build']}")
    by_defect = {}
    for report in failed:
        by_defect.setdefault(report.known_defect, []).append(report.nodeid.split("::")[-1])
    for defect, names in sorted(by_defect.items()):
        terminalreporter.write_line(f"{defect}  {', '.join(names)}")
