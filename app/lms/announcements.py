"""Dashboard Latest Announcements, including announcements outside course cards."""

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page

from app.config import LMS_URL
from app.lms.auth import is_authenticated
from app.lms.models import Announcement

NEWS_PATH = "/web/Uzem/News/ReadNews"
COURSE_CODE = re.compile(r"^([A-Z]{2,4}\d{3})\b")


def dashboard_announcements(page: Page) -> list[tuple[str, Announcement]]:
    if not is_authenticated(page):
        raise RuntimeError("SESSION_EXPIRED")
    heading = page.locator("h2").filter(has_text="Latest Announcements").first
    if heading.count() != 1:
        raise RuntimeError("DASHBOARD_NEWS_NOT_FOUND")
    card = heading.locator(
        'xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," yoo-card ")][1]'
    )
    base = urlparse(LMS_URL)
    entries: list[tuple[str, str, str]] = []
    for row in card.locator("tbody tr").all():
        link = row.locator("a").first
        url = link.get_attribute("href") or ""
        parsed = urlparse(url)
        news_id = parse_qs(parsed.query).get("NewsID", [])
        if (
            parsed.scheme != "https"
            or parsed.netloc != base.netloc
            or parsed.path != NEWS_PATH
            or len(news_id) != 1
            or not news_id[0].isdigit()
        ):
            raise RuntimeError("NEWS_LINK_INVALID")
        title = link.evaluate(
            '(e)=>[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(" ").trim()'
        )
        entries.append((title, row.locator("td").last.inner_text().strip(), url))
    results: list[tuple[str, Announcement]] = []
    for title, posted_at, url in entries:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        card = page.locator(".yoo-card").filter(has=page.locator(".uzem-news-detail-heading"))
        if card.count() != 1:
            raise RuntimeError("NEWS_DETAILS_NOT_FOUND")
        tags = card.locator(".uzem-news-course-tag").all_inner_texts()
        match = COURSE_CODE.search(tags[0].strip()) if tags else None
        code = match.group(1) if match else "GLOBAL"
        content = card.locator(".yoo-card-body").first.inner_text().strip()
        results.append((code, Announcement(title, posted_at, url, content)))
    return results
