"""Dedicated persistent Chromium context for manual LMS authentication."""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
from app.lms.auth import is_authenticated


class LoginError(RuntimeError):
    """Login could not be verified."""


@contextmanager
def authenticated_context(
    profile_path: Path = PROFILE_PATH, *, accept_downloads: bool = False
) -> Iterator[BrowserContext]:
    """Open saved session for read-only LMS queries."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PROJECT_ROOT / "browser-binaries")
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path, headless=True, accept_downloads=accept_downloads
        )
        try:
            yield context
        finally:
            context.close()


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
def authenticated_uzem_context() -> Iterator[BrowserContext]:
    """Restore UZEM's session cookie for read-only portal requests."""
    session_path = UZEM_PROFILE_PATH / "session.json"
    if not session_path.is_file():
        raise LoginError("UZEM_SESSION_MISSING: run `python -m app.cli uzem-login`")
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
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=UZEM_PROFILE_PATH, headless=True, accept_downloads=False
        )
        try:
            context.add_cookies(cookies)
            yield context
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
        if "ewi.altinbas.edu.tr" not in page.url.casefold():
            return False
        if page.locator('input[type="password"]:visible').count() > 0:
            return False
        return page.locator('a[href*="/web/Ogrenci/Dersler/Derslerim"]').count() > 0
    except Error:
        return False


def is_any_authenticated(page) -> bool:
    """Recognize either university product for the shared manual-login helper."""
    return is_authenticated(page) or is_ewi_authenticated(page)
