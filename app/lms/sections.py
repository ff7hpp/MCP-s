"""Read-only notification, live lesson and study link metadata."""

from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from app.errors import ActionableError
from app.lms.readonly import NEXT_SELECTOR, iter_pages, request_allowed

NOTIFICATIONS_URL = "https://lms.altinbas.edu.tr/web/Uzem/Notification"


def catalogue(page, *, followed_only=True, page_number=1, search=""):
    if (
        type(followed_only) is not bool
        or type(page_number) is not int
        or not 1 <= page_number <= 1000
        or not isinstance(search, str)
        or len(search) > 100
    ):
        raise ValueError("CATALOGUE_ARGUMENT_INVALID")
    url = "https://lms.altinbas.edu.tr/web/Uzem/Ogrenci/DersKatalogu?" + urlencode(
        {"Search": search, "TakipEdilenler": int(followed_only), "ShowPage": page_number}
    )
    if not request_allowed("GET", url, navigation=True):
        raise ValueError("CATALOGUE_ARGUMENT_INVALID")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    table = page.locator("#table_UZEM_CatalogCourses")
    if table.count() != 1:
        raise ActionableError("CATALOGUE_LAYOUT_CHANGED")
    items = []
    for row in table.locator("tbody tr").all():
        cells = row.locator("td").all_inner_texts()
        if len(cells) == 1 and row.locator("td[colspan]").count() and "no " in cells[0].casefold():
            continue
        control = row.locator("button.uzem-catalog-follow")
        if (
            len(cells) != 4
            or control.count() != 1
            or not (control.get_attribute("data-ders-id") or "").isdigit()
        ):
            raise ActionableError("CATALOGUE_ROW_LAYOUT_CHANGED")
        items.append(
            {
                "remote_id": control.get_attribute("data-ders-id"),
                "course_code": cells[1].replace("▸", "").strip(),
                "title": cells[2].strip(),
                "followed": control.get_attribute("aria-pressed") == "true",
                "resource_count": cells[3].strip(),
                "url": url,
                "enrollment_status": "Unknown; catalogue follow is separate from enrollment",
            }
        )
    stats = {}
    for key, selector in (
        ("catalogue_courses", "#UzemCatalogTotalCourses"),
        ("followed_courses", "#UzemCatalogFollowedCourses"),
        ("shared_resources", "#UzemCatalogTotalResources"),
    ):
        value = page.locator(selector).inner_text().strip()
        if not value.isdigit():
            raise ActionableError("CATALOGUE_STATS_LAYOUT_CHANGED")
        stats[key] = int(value)
    return {
        "items": items,
        "stats": stats,
        "source_url": url,
        "page": page_number,
        "has_more": bool(page.locator(NEXT_SELECTOR).count()),
        "scope": "Followed courses"
        if followed_only
        else "Catalogue page; not enrolled course list",
    }


def notifications(page):
    page.goto(NOTIFICATIONS_URL, wait_until="domcontentloaded", timeout=30000)
    items, seen = [], set()
    for _ in iter_pages(page):
        table = page.locator("#table_UZEM_NOTIFICATION_LIST")
        if table.count() != 1:
            raise ActionableError("NOTIFICATION_LAYOUT_CHANGED")
        for row in table.locator("tbody tr").all():
            cells = row.locator("td")
            if (
                cells.count() == 1
                and cells.first.get_attribute("colspan")
                and "no " in cells.first.inner_text().casefold()
            ):
                continue
            link = row.locator("a").first
            href = urljoin(page.url, link.get_attribute("href") or "")
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "lms.altinbas.edu.tr"
                or parsed.path != "/web/Uzem/Notification/Redirect"
                or set(query) != {"NID"}
                or len(query["NID"]) != 1
                or not query["NID"][0].isdigit()
                or cells.count() != 2
            ):
                raise ActionableError("NOTIFICATION_ITEM_LAYOUT_CHANGED")
            remote_id = query["NID"][0]
            if remote_id in seen:
                raise ActionableError("DUPLICATE_NOTIFICATION_ID")
            seen.add(remote_id)
            title = link.evaluate(
                '(e)=>[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(" ").trim()'
            )
            items.append(
                {
                    "remote_id": remote_id,
                    "title": title,
                    "date": cells.nth(1).inner_text().strip(),
                    "unread": "font-weight-bold" in (row.get_attribute("class") or "").split(),
                    "url": NOTIFICATIONS_URL,
                    "redirect_url": href,
                    "link_policy": "Redirect may mark read; never follow automatically",
                }
            )
    return items


def course_links(page):
    """Extract only; external links and join controls are never opened."""
    lessons = page.locator(".uzem-student-live-list")
    notebook = page.locator(".uzem-notebooklm-panel")
    if lessons.count() != 1 or notebook.count() != 1:
        raise ActionableError("COURSE_LINKS_LAYOUT_CHANGED")
    live = []
    for row in lessons.locator(".uzem-live-row, .uzem-live-item, .uzem-live-lesson").all():
        live.append(
            {"title": row.inner_text().strip(), "url": page.url, "links": _links(row, page.url)}
        )
    if not live and not lessons.locator(".uzem-course-empty-row").count():
        live.append(
            {
                "title": lessons.inner_text().strip(),
                "url": page.url,
                "links": _links(lessons, page.url),
                "fields_status": "Raw source only; exact schedule fields unknown",
            }
        )
    study = _links(notebook, page.url)
    return live, study


def _links(container, base):
    links = []
    for link in container.locator("a[href], [data-join-url]").all():
        href = urljoin(
            base, link.get_attribute("data-join-url") or link.get_attribute("href") or ""
        )
        if urlparse(href).scheme == "https" and not urlparse(href).username:
            links.append({"title": link.inner_text().strip(), "url": href})
    return links
