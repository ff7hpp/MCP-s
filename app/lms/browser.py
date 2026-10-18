"""Dedicated persistent Chromium context for manual LMS authentication."""

import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import BrowserContext, Error, sync_playwright

from app.config import (
    EWI_PROFILE_PATH,
    EWI_URL,
    LMS_URL,
    PROFILE_PATH,
    PROJECT_ROOT,
    UZEM_PROFILE_PATH,
    UZEM_URL,
)
from app.errors import ActionableError
from app.lms.auth import is_authenticated
from app.lms.credentials import saved_credentials
from app.lms.readonly import STATIC, assert_readonly, protect_context, request_allowed
from app.storage.state import operation_lock, serialized


class LoginError(ActionableError):
    """Login could not be verified."""


_AUTO_LOGIN_RETRY_AFTER: dict[str, float] = {}


def _auto_login(context: BrowserContext, portal: str) -> None:
    """Try one bounded sign-in using the local Windows vault before read-only routing."""
    target = {"LMS": LMS_URL, "EWI": EWI_URL, "UZEM": UZEM_URL}[portal]
    authenticated = {
        "LMS": is_authenticated,
        "EWI": is_ewi_authenticated,
        "UZEM": is_uzem_authenticated,
    }[portal]
    page = context.pages[0] if context.pages else context.new_page()
    attempted = False
    login_post_allowed = False

    def login_guard(route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        portal_get = request_allowed(
            request.method, request.url, navigation=request.is_navigation_request()
        )
        sign_in_get = (
            request.method in {"GET", "HEAD"}
            and parsed.scheme == "https"
            and (
                (
                    parsed.hostname == "sso.altinbas.edu.tr"
                    and (parsed.path == "/" or bool(STATIC.search(parsed.path)))
                )
                or (
                    portal == "UZEM"
                    and parsed.hostname == "uzem.altinbas.edu.tr"
                    and parsed.path == "/login/index.php"
                )
            )
        )
        sign_in_post = (
            login_post_allowed
            and request.method == "POST"
            and parsed.scheme == "https"
            and parsed.hostname == expected_host
            and parsed.path == expected_path
        )
        if portal_get or sign_in_get or sign_in_post:
            route.fallback()
        else:
            route.abort("blockedbyclient")

    context.route("**/*", login_guard)
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
        if authenticated(page):
            return
        if time.monotonic() < _AUTO_LOGIN_RETRY_AFTER.get(portal, 0):
            raise LoginError(f"{portal}_AUTO_LOGIN_COOLDOWN: use visible manual sign-in")
        credentials = saved_credentials()
        if credentials is None:
            raise LoginError(f"{portal}_SESSION_EXPIRED: use visible manual sign-in")
        expected_host = "uzem.altinbas.edu.tr" if portal == "UZEM" else "sso.altinbas.edu.tr"
        expected_path = "/login/index.php" if portal == "UZEM" else "/"
        current = urlparse(page.url)
        if (
            current.scheme != "https"
            or current.hostname != expected_host
            or current.path != expected_path
        ):
            raise LoginError(f"{portal}_AUTO_LOGIN_UNAVAILABLE: use visible manual sign-in")
        form = (
            page.locator("form#login")
            if portal == "UZEM"
            else page.locator('form:has(input[name="sso[UserName]"])')
        )
        if form.count() != 1 or (form.get_attribute("method") or "").casefold() != "post":
            raise LoginError(f"{portal}_AUTO_LOGIN_UNAVAILABLE: use visible manual sign-in")
        action = urlparse(urljoin(page.url, form.get_attribute("action") or ""))
        if (
            action.scheme != "https"
            or action.hostname != expected_host
            or action.path != expected_path
        ):
            raise LoginError(f"{portal}_AUTO_LOGIN_UNAVAILABLE: use visible manual sign-in")
        user_selector = "#username" if portal == "UZEM" else 'input[name="sso[UserName]"]'
        password_selector = "#password" if portal == "UZEM" else 'input[name="sso[PassWord]"]'
        if form.locator(user_selector).count() != 1 or form.locator(password_selector).count() != 1:
            raise LoginError(f"{portal}_AUTO_LOGIN_UNAVAILABLE: use visible manual sign-in")
        form.locator(user_selector).fill(credentials[0])
        form.locator(password_selector).fill(credentials[1])
        attempted = True
        login_post_allowed = True
        form.locator('button[type="submit"], input[type="submit"]').first.click(timeout=15000)
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
        if not authenticated(page):
            if page.locator(
                'input[autocomplete="one-time-code"], input[name*="otp" i], iframe[title*="captcha" i], .g-recaptcha'
            ).count():
                raise LoginError(
                    f"{portal}_MANUAL_CHALLENGE_REQUIRED: MFA or CAPTCHA; use visible manual sign-in"
                )
            messages = " ".join(
                page.locator('.alert-danger, [role="alert"], .login-errors').all_inner_texts()
            )
            reason = (
                "CREDENTIALS_REJECTED"
                if re.search(
                    r"invalid credentials|incorrect password|invalid username|hatalı.*(?:şifre|kullanıcı)",
                    messages,
                    re.IGNORECASE,
                )
                else "AUTHENTICATION_UNCONFIRMED"
            )
            raise LoginError(
                f"{portal}_AUTO_LOGIN_FAILED: reason={reason}; use visible manual sign-in"
            )
        if portal == "UZEM":
            _save_uzem_session(context, UZEM_PROFILE_PATH / "session.json")
    except LoginError:
        if attempted:
            _AUTO_LOGIN_RETRY_AFTER[portal] = time.monotonic() + 900
        raise
    except Error:
        if attempted:
            _AUTO_LOGIN_RETRY_AFTER[portal] = time.monotonic() + 900
            raise LoginError(
                f"{portal}_AUTO_LOGIN_FAILED: reason=NETWORK_OR_NAVIGATION_FAILURE; use visible manual sign-in"
            ) from None
        raise LoginError(f"{portal}_PORTAL_UNAVAILABLE: login page could not be reached") from None
    finally:
        context.unroute("**/*", login_guard)


@contextmanager
def authenticated_context(
    profile_path: Path = PROFILE_PATH, *, accept_downloads: bool = False
) -> Iterator[BrowserContext]:
    """Open saved session for read-only LMS queries."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with operation_lock(), sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=True,
            accept_downloads=accept_downloads,
            service_workers="block",
            args=["--no-startup-window", "--disable-logging"],
        )
        try:
            _auto_login(context, "EWI" if profile_path == EWI_PROFILE_PATH else "LMS")
            protect_context(context)
            yield context
            assert_readonly(context)
        finally:
            context.close()


@serialized
def manual_login(profile_path: Path = PROFILE_PATH, timeout_seconds: int = 900) -> None:
    profile_path.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path, headless=False, accept_downloads=False
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(LMS_URL, wait_until="domcontentloaded", timeout=30000)
                print("LMS opened. Sign in manually in this browser window.", flush=True)
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if any(is_authenticated(open_page) for open_page in context.pages):
                        print("LMS authentication successful. Session stored locally.")
                        return
                    if page.is_closed():
                        raise LoginError("Browser page closed before login was verified")
                    page.wait_for_timeout(1000)
                raise LoginError("Login not verified within 15 minutes")
            finally:
                context.close()
    except Error as exc:
        raise LoginError(f"Browser failed: {exc.message.splitlines()[0]}") from exc


@serialized
def manual_ewi_login(profile_path: Path = EWI_PROFILE_PATH, timeout_seconds: int = 900) -> None:
    """Open EWI in a visible browser for manual authentication."""
    profile_path.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path, headless=False, accept_downloads=False
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(EWI_URL, wait_until="domcontentloaded", timeout=30000)
                print("EWI opened. Sign in manually in this browser window.", flush=True)
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if any(is_ewi_authenticated(open_page) for open_page in context.pages):
                        print("EWI authentication successful. Session stored locally.")
                        return
                    if page.is_closed():
                        raise LoginError("EWI browser page closed before login was verified")
                    page.wait_for_timeout(1000)
                raise LoginError("EWI login not verified within 15 minutes")
            finally:
                context.close()
    except Error as exc:
        raise LoginError(f"EWI browser failed: {exc.message.splitlines()[0]}") from exc


@serialized
def manual_uzem_login(profile_path: Path = UZEM_PROFILE_PATH, timeout_seconds: int = 900) -> None:
    """Open the old UZEM site in its own browser for manual sign-in."""
    profile_path.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path, headless=False, accept_downloads=False
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(UZEM_URL, wait_until="domcontentloaded", timeout=30000)
                print("UZEM opened. Sign in manually in this browser window.", flush=True)
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if any(is_uzem_authenticated(open_page) for open_page in context.pages):
                        _save_uzem_session(context, profile_path / "session.json")
                        print("UZEM authentication successful. Session stored locally.")
                        return
                    if page.is_closed():
                        raise LoginError("UZEM browser page closed before login was verified")
                    page.wait_for_timeout(1000)
                raise LoginError("UZEM login not verified within 15 minutes")
            finally:
                context.close()
    except Error as exc:
        raise LoginError(f"UZEM browser failed: {exc.message.splitlines()[0]}") from exc


def _save_uzem_session(context: BrowserContext, path: Path) -> None:
    """Persist only the UZEM Moodle session cookie inside the ignored profile."""
    cookies = [
        cookie
        for cookie in context.cookies([UZEM_URL])
        if cookie["name"] == "MoodleSession"
        and cookie["domain"].lstrip(".").casefold() == "uzem.altinbas.edu.tr"
    ]
    if len(cookies) != 1:
        raise LoginError("UZEM_SESSION_MISSING: Moodle session cookie was not available")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def authenticated_uzem_context(*, accept_downloads: bool = False) -> Iterator[BrowserContext]:
    """Restore UZEM's session cookie for read-only portal requests."""
    session_path = UZEM_PROFILE_PATH / "session.json"
    if not session_path.is_file() and saved_credentials() is None:
        raise LoginError("UZEM_SESSION_MISSING: run `python -m app.cli uzem-login`")
    cookies = []
    if session_path.is_file():
        try:
            cookies = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoginError("UZEM_SESSION_INVALID: run `python -m app.cli uzem-login`") from exc
        if not isinstance(cookies, list) or len(cookies) != 1:
            raise LoginError("UZEM_SESSION_INVALID: run `python -m app.cli uzem-login`")
        cookie = cookies[0]
        if (
            not isinstance(cookie, dict)
            or cookie.get("name") != "MoodleSession"
            or str(cookie.get("domain", "")).lstrip(".").casefold() != "uzem.altinbas.edu.tr"
        ):
            raise LoginError("UZEM_SESSION_INVALID: run `python -m app.cli uzem-login`")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with operation_lock(), sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=UZEM_PROFILE_PATH,
            headless=True,
            accept_downloads=accept_downloads,
            service_workers="block",
            args=["--no-startup-window", "--disable-logging"],
        )
        try:
            if cookies:
                context.add_cookies(cookies)
            _auto_login(context, "UZEM")
            protect_context(context)
            yield context
            assert_readonly(context)
            if any(is_uzem_authenticated(page) for page in context.pages):
                _save_uzem_session(context, session_path)
        finally:
            context.close()


def is_uzem_authenticated(page) -> bool:
    """Require a UZEM page with Moodle's signed-in user navigation."""
    try:
        if not page.url.casefold().startswith("https://uzem.altinbas.edu.tr/"):
            return False
        if "/login/" in page.url.casefold():
            return False
        if page.locator('input[type="password"]:visible').count() > 0:
            return False
        return (
            page.locator(
                '#user-menu, [data-region="user-menu"], a[href*="/login/logout.php"]'
            ).count()
            > 0
        )
    except Error:
        return False


def is_ewi_authenticated(page) -> bool:
    """Require the authenticated EWI navigation and reject login/password pages."""
    try:
        if not page.url.casefold().startswith("https://ewi.altinbas.edu.tr/"):
            return False
        if page.locator('input[type="password"]:visible').count() > 0:
            return False
        return page.locator('a[href*="/web/Ogrenci/Dersler/Derslerim"]').count() > 0
    except Error:
        return False
