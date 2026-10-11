"""Dedicated persistent Chromium context for manual LMS authentication."""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, Error, sync_playwright

from app.config import EWI_PROFILE_PATH, EWI_URL, LMS_URL, PROFILE_PATH, PROJECT_ROOT
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
