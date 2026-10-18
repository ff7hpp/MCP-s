"""Conservative authenticated-page signal; refine after live LMS inspection."""

from playwright.sync_api import Error, Page


def is_authenticated(page: Page) -> bool:
    """Require a course navigation signal and absence of visible password input."""
    try:
        if not page.url.casefold().startswith("https://lms.altinbas.edu.tr/"):
            return False
        password_visible = page.locator('input[type="password"]:visible').count() > 0
        course_nav_visible = page.get_by_text("My Courses", exact=True).first.is_visible()
        return course_nav_visible and not password_visible
    except Error:
        return False
