"""Complete paginated LMS news lists with isolated detail failures."""

import re
from dataclasses import replace
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Page

from app.errors import ActionableError
from app.lms.models import Announcement
from app.lms.readonly import iter_pages, request_allowed

NEWS_PATH = "/web/Uzem/News/ReadNews"
COURSE_CODE = re.compile(r"^([A-Z]{2,4}\d{3})\b")


def news_list(page: Page, course=None, errors=None) -> list[Announcement]:
    errors = errors if errors is not None else {}
    url = "https://lms.altinbas.edu.tr/web/Uzem/News/NewsList"
    if course:
        url += "?SID=" + parse_qs(urlparse(course.url).query)["SID"][0]
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    entries, seen = [], set()
    try:
        for _ in iter_pages(page):
            table = page.locator("#table_UZEM_NEWS_LIST")
            if table.count() != 1:
                empty = page.locator(".yoo-content .yoo-card-body p").filter(
                    has_text=re.compile(r"^No published announcements were found\.$")
                )
                if empty.count() == 1:
                    continue
                raise ActionableError("NEWS_LIST_LAYOUT_CHANGED")
            for index, row in enumerate(table.locator("tbody tr").all()):
                try:
                    cells = row.locator("td").all_inner_texts()
                    if (
                        len(cells) == 1
                        and row.locator("td[colspan]").count()
                        and "no " in cells[0].casefold()
                    ):
                        continue
                    link = row.locator("a").first
                    if not link.count():
                        raise ActionableError("NEWS_LINK_MISSING")
                    href = urljoin(page.url, link.get_attribute("href") or "")
                    query = parse_qs(urlparse(href).query)
                    if (
                        not request_allowed("GET", href, navigation=True)
                        or urlparse(href).path != NEWS_PATH
                        or len(query.get("NewsID", [])) != 1
                        or not query["NewsID"][0].isdigit()
                        or len(cells) < 2
                    ):
                        raise ActionableError("NEWS_LINK_INVALID")
                    if query["NewsID"][0] not in seen:
                        seen.add(query["NewsID"][0])
                        entries.append(
                            Announcement(link.inner_text().strip(), cells[1].strip(), href)
                        )
                except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
                    errors[f"announcements:row:{index}"] = (
                        f"NEWS_LIST_ITEM_FAILED: {type(exc).__name__}"
                    )
    except Exception as exc:
        if not entries:
            raise
        errors["announcements:list"] = f"LIST_PAGINATION_FAILED: {type(exc).__name__}"
    return entries


def dashboard_announcements(page: Page, errors=None) -> list[tuple[str, Announcement]]:
    """Read All Announcements, including news outside enrolled course cards."""
    from app.lms.scanner import _announcement_detail

    errors = errors if errors is not None else {}
    results = []
    for item in news_list(page, errors=errors):
        try:
            detailed = _announcement_detail(page, item)
            tags = page.locator(".uzem-news-course-tag").all_inner_texts()
            match = COURSE_CODE.search(tags[0].strip()) if tags else None
            results.append((match[1] if match else "GLOBAL", detailed))
        except Exception as exc:  # noqa: BLE001 - isolate untrusted portal section or item
            error = f"NEWS_DETAIL_FAILED: {type(exc).__name__}"
            errors[f"announcements:{item.url}"] = error
            results.append(("GLOBAL", replace(item, detail_error=error)))
    return results
