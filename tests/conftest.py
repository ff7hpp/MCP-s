import os

import pytest
from playwright.sync_api import sync_playwright

from app.config import PROJECT_ROOT
from app.drive import cloud, records
from app.lms.readonly import protect_context
from app.services import health
from app.storage import state


@pytest.fixture(autouse=True)
def isolated_sync_receipts(monkeypatch, tmp_path):
    monkeypatch.setattr(records, "STATE_PATH", tmp_path / "receipts.json")
    monkeypatch.setattr(state, "LOCK_PATH", tmp_path / "operation.lock")
    monkeypatch.setattr(cloud, "STATE_PATH", tmp_path / "cloud_verifications.json")
    monkeypatch.setattr(health, "METRICS_PATH", tmp_path / "operational_health.json")


@pytest.fixture(scope="module")
def chromium():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def offline(chromium):
    routes = {}
    context = chromium.new_context()
    context.route(
        "**/*",
        lambda route: route.fulfill(
            body=routes.get(route.request.url, "<h1>Missing fixture</h1>"), content_type="text/html"
        ),
    )
    protect_context(context)
    page = context.new_page()
    yield context, page, routes
    context.close()
