"""Offline authentication-flow checks; all credentials and pages are synthetic."""

import os
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

from app.config import PROJECT_ROOT
from app.lms import browser as auth


def redirect(route, target):
    """Make a new routed navigation; fulfilled 302s can bypass Playwright routes."""
    route.fulfill(body=f'<script>location.replace("{target}")</script>', content_type="text/html")


@pytest.fixture
def context():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        session = browser.new_context()
        yield session
        session.close()
        browser.close()


def test_ewi_auto_login_submits_once_then_reads_authenticated_portal(context, monkeypatch):
    monkeypatch.setattr(auth, "saved_credentials", lambda: ("student-test", "password-test"))
    state = {"authenticated": False, "submissions": 0}

    def respond(route):
        request = route.request
        host = urlparse(request.url).hostname
        if host == "ewi.altinbas.edu.tr":
            if state["authenticated"]:
                route.fulfill(
                    body='<a href="/web/Ogrenci/Dersler/Derslerim">Courses</a>',
                    content_type="text/html",
                )
            else:
                redirect(route, "https://sso.altinbas.edu.tr/")
        elif host == "sso.altinbas.edu.tr" and request.method == "POST":
            state["submissions"] += 1
            assert "password-test" in request.post_data
            state["authenticated"] = True
            redirect(route, "https://ewi.altinbas.edu.tr/web/Main")
        elif host == "sso.altinbas.edu.tr":
            route.fulfill(
                body="""<form method="post"><input name="sso[UserName]">
                    <input type="password" name="sso[PassWord]"><input type="submit"></form>""",
                content_type="text/html",
            )
        else:
            route.fulfill(body="", content_type="text/plain")

    context.route("**/*", respond)
    auth._auto_login(context, "EWI")
    assert state["submissions"] == 1
    assert auth.is_ewi_authenticated(context.pages[0])
    auth._auto_login(context, "EWI")
    assert state["submissions"] == 1


def test_auto_login_rejects_unexpected_sign_in_origin(context, monkeypatch):
    monkeypatch.setattr(auth, "saved_credentials", lambda: ("student-test", "password-test"))
    submitted = []

    def respond(route):
        request = route.request
        if request.method == "POST":
            submitted.append(request.url)
        if urlparse(request.url).hostname == "ewi.altinbas.edu.tr":
            redirect(route, "https://lms.altinbas.edu.tr/login")
        else:
            route.fulfill(body="<form method='post'><input type='password'></form>")

    context.route("**/*", respond)
    with pytest.raises(auth.LoginError, match="AUTO_LOGIN_UNAVAILABLE"):
        auth._auto_login(context, "EWI")
    assert submitted == []


def test_uzem_auto_login_verifies_portal_and_saves_session(context, monkeypatch):
    monkeypatch.setattr(auth, "saved_credentials", lambda: ("student-test", "password-test"))
    saved = []
    monkeypatch.setattr(auth, "_save_uzem_session", lambda *args: saved.append(True))
    state = {"authenticated": False, "submissions": 0}

    def respond(route):
        request = route.request
        if request.method == "POST":
            state["submissions"] += 1
            state["authenticated"] = True
            redirect(route, "https://uzem.altinbas.edu.tr/my/courses.php")
        elif "/login/index.php" in request.url:
            route.fulfill(
                body="""<form id="login" method="post" action="/login/index.php">
                    <input id="username"><input id="password" type="password">
                    <button type="submit">Sign in</button></form>""",
                content_type="text/html",
            )
        elif state["authenticated"]:
            route.fulfill(body='<div id="user-menu">Student</div>', content_type="text/html")
        else:
            redirect(route, "https://uzem.altinbas.edu.tr/login/index.php")

    context.route("**/*", respond)
    auth._auto_login(context, "UZEM")
    assert state["submissions"] == 1
    assert saved == [True]


def test_failed_login_does_not_repeat_credentials_in_same_process(context, monkeypatch):
    monkeypatch.setattr(auth, "saved_credentials", lambda: ("student-test", "wrong-test"))
    monkeypatch.setattr(auth, "_AUTO_LOGIN_RETRY_AFTER", {})
    submissions = []

    def respond(route):
        request = route.request
        if request.method == "POST":
            submissions.append(True)
            route.fulfill(body="Login failed", content_type="text/html")
        elif urlparse(request.url).hostname == "ewi.altinbas.edu.tr":
            redirect(route, "https://sso.altinbas.edu.tr/")
        else:
            route.fulfill(
                body="""<form method="post"><input name="sso[UserName]">
                    <input type="password" name="sso[PassWord]"><input type="submit"></form>""",
                content_type="text/html",
            )

    context.route("**/*", respond)
    with pytest.raises(auth.LoginError, match="AUTO_LOGIN_FAILED"):
        auth._auto_login(context, "EWI")
    with pytest.raises(auth.LoginError, match="AUTO_LOGIN_COOLDOWN"):
        auth._auto_login(context, "EWI")
    assert submissions == [True]


def test_unreachable_portal_is_not_reported_as_rejected_credentials(context, monkeypatch):
    monkeypatch.setattr(auth, "saved_credentials", lambda: ("student-test", "password-test"))
    monkeypatch.setattr(auth, "_AUTO_LOGIN_RETRY_AFTER", {})
    context.route("**/*", lambda route: route.abort("timedout"))
    with pytest.raises(auth.LoginError, match="UZEM_PORTAL_UNAVAILABLE"):
        auth._auto_login(context, "UZEM")
    assert "UZEM" not in auth._AUTO_LOGIN_RETRY_AFTER


def test_valid_manual_session_never_reads_vault_even_during_cooldown(context, monkeypatch):
    def forbidden():
        pytest.fail("Valid manual session must not depend on credential storage")

    monkeypatch.setattr(auth, "saved_credentials", forbidden)
    monkeypatch.setattr(auth, "_AUTO_LOGIN_RETRY_AFTER", {"EWI": time.monotonic() + 900})
    context.route(
        "**/*",
        lambda route: route.fulfill(
            body='<a href="/web/Ogrenci/Dersler/Derslerim">Courses</a>', content_type="text/html"
        ),
    )
    auth._auto_login(context, "EWI")
    assert auth.is_ewi_authenticated(context.pages[0])


def test_non_windows_vault_is_optional(monkeypatch):
    from app.lms import credentials

    monkeypatch.setattr(credentials.sys, "platform", "linux")
    assert credentials.saved_credentials() is None
