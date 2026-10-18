"""Fail-closed browser request guard and bounded, validated GET pagination."""

import json
import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

from app.errors import ActionableError

HOSTS = {"lms.altinbas.edu.tr", "ewi.altinbas.edu.tr", "uzem.altinbas.edu.tr"}
ASSET_HOSTS = {
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "code.jquery.com",
}
WRITE = re.compile(
    r"(?:logout|mark.?read|delete|remove|submit|enrol|unenrol|approve|cancel|update|save|setpref)",
    re.IGNORECASE,
)
EWI_SECTION_PATHS = {
    "home": "/web/Main",
    "course_selection": "/web/DersSecimi/DonemDersSecimi",
    "course_resources": "/web/Ogrenci/Dersler/DersKaynaklari",
    "my_courses": "/web/Ogrenci/Dersler/Derslerim",
    "schedules": "/web/Ogrenci/Program/DersProgrami",
    "curriculum": "/web/Ogrenci/Dersler/BolumDersleri",
    "exam_results": "/web/Ogrenci/Sonuclar/SinavSonuclari",
    "absences": "/web/Ogrenci/Dersler/Devamsizlik",
    "transcript": "/web/Ogrenci/Transkript",
    "document_requests": "/web/Flow/Ogrenci/BelgeTalepListesi",
    "transfer_documents": "/web/Flow/Ogrenci/YatayGecisBelgeBasvurusu",
    "finance_information": "/web/Finans/Sozlesme/info",
    "registration_information": "/web/Ogrenci/Bilgiler/KayitBilgileri",
    "surveys": "/web/Survey",
    "messages": "/web/Message",
    "notifications": "/web/Platform/Notification",
    "news": "/web/News/NewsList",
}
READ_PATHS = {
    "lms.altinbas.edu.tr": {
        "/web/Uzem",
        "/web/Uzem/Ogrenci/Dersler/Derslerim",
        "/web/Uzem/Ogrenci/Dersler/DersDetay",
        "/web/Uzem/Ogrenci/Dersler/DersKaynaklari",
        "/web/Uzem/News/ReadNews",
        "/web/Uzem/News/NewsList",
        "/web/Uzem/Ogrenci/Dersler/Odevler",
        "/web/Uzem/Notification",
        "/web/Uzem/Ogrenci/DersKatalogu",
    },
    "ewi.altinbas.edu.tr": {*EWI_SECTION_PATHS.values(), "/web/News/ReadNews"},
    "uzem.altinbas.edu.tr": {
        "/my/",
        "/my/courses.php",
        "/course/view.php",
        "/mod/resource/view.php",
        "/mod/forum/view.php",
        "/message/output/popup/notifications.php",
        "/calendar/view.php",
        "/grade/report/user/index.php",
    },
}
READ_QUERY_KEYS = {
    "sid",
    "crid",
    "downloadfile",
    "newsid",
    "showpage",
    "id",
    "page",
    "perpage",
    "offset",
    "limit",
    "view",
    "time",
    "lang",
    "forcedownload",
    "action",
    "odevid",
    "viewfile",
}
STATIC = re.compile(
    r"\.(?:css|js|map|png|jpe?g|gif|svg|ico|woff2?|ttf|otf|eot)(?:/|$)", re.IGNORECASE
)
NEXT_SELECTOR = 'a[rel="next"]:not([aria-disabled="true"]), .pagination li:not(.disabled) a[aria-label="Next"], .pagination li.next:not(.disabled) a, .pagination li:not(.disabled) a:has-text("keyboard_arrow_right")'
DYNAMIC_NEXT_SELECTOR = '[data-action="next"]:not([disabled]):not(.disabled), .pagination .next:not(.disabled) button:not([disabled])'


def require_single_page(page) -> None:
    if page.locator(NEXT_SELECTOR).count() or page.locator(DYNAMIC_NEXT_SELECTOR).count():
        raise ActionableError(
            "PAGINATION_UNSUPPORTED: this layout needs a verified page reader; scan incomplete"
        )


def request_allowed(
    method: str, url: str, *, navigation: bool = False, post_data: str | None = None
) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in HOSTS | ASSET_HOSTS or parsed.params:
        return False
    path = unquote(parsed.path)
    if (
        re.search(r"%[0-9a-f]{2}", path, re.IGNORECASE)
        or "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        return False
    if (
        method == "GET"
        and parsed.netloc == "uzem.altinbas.edu.tr"
        and path == "/lib/ajax/service-nologin.php"
    ):
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            set(query) - {"info", "cachekey", "args"}
            or query.get("info") != ["core_get_string"]
            or len(query.get("args", [])) != 1
            or len(query["args"][0]) > 64_000
        ):
            return False
        try:
            calls = json.loads(query["args"][0])
        except ValueError:
            return False
        return (
            isinstance(calls, list)
            and 0 < len(calls) <= 20
            and all(
                isinstance(call, dict)
                and call.get("methodname") == "core_get_string"
                and isinstance(call.get("args"), dict)
                and not set(call["args"]) - {"stringid", "component", "lang", "a", "stringparams"}
                for call in calls
            )
        )
    if (
        method == "POST"
        and parsed.scheme == "https"
        and parsed.netloc == "uzem.altinbas.edu.tr"
        and path == "/lib/ajax/service.php"
    ):
        if len(post_data or "") > 64_000:
            return False
        try:
            calls = json.loads(post_data or "")
        except ValueError:
            return False
        return (
            isinstance(calls, list)
            and 0 < len(calls) <= 20
            and all(
                isinstance(call, dict)
                and call.get("methodname")
                in {
                    "core_course_get_enrolled_courses_by_timeline_classification",
                    "core_courseformat_get_state",
                }
                and isinstance(call.get("args"), dict)
                and not any(WRITE.search(key) for key in call["args"])
                for call in calls
            )
        )
    if method not in {"GET", "HEAD"}:
        return False
    if navigation and (parsed.scheme != "https" or parsed.netloc not in HOSTS):
        return False
    if parsed.hostname in HOSTS:
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.netloc == "ewi.altinbas.edu.tr" and path == "/web/News/ReadNews/Main/GetImage":
            # Observed embedded news image request; never a navigation or action URL.
            return (
                not navigation
                and set(query) == {"NewsID", "FileID"}
                and all(
                    len(values) == 1
                    and values[0].isascii()
                    and values[0].isdigit()
                    and 0 < len(values[0]) <= 20
                    for values in query.values()
                )
            )
        if parsed.netloc == "lms.altinbas.edu.tr" and path == "/web/Uzem/Ogrenci/DersKatalogu":
            if set(query) - {"Search", "TakipEdilenler", "ShowPage"} or any(
                len(value) != 1 for value in query.values()
            ):
                return False
            if query.get("TakipEdilenler", ["0"])[0] not in {"0", "1"}:
                return False
            page_number = query.get("ShowPage", ["1"])[0]
            search = query.get("Search", [""])[0]
            return (
                page_number.isascii()
                and page_number.isdigit()
                and 1 <= int(page_number) <= 1000
                and len(search) <= 100
                and not any(ord(char) < 32 for char in search)
            )
        if parsed.netloc == "lms.altinbas.edu.tr" and path in {
            "/web/Uzem/Ogrenci/Dersler/Odevler",
            "/web/Uzem/News/NewsList",
            "/web/Uzem/Notification",
        }:
            # Observed assignment list/details only; no form posts or action aliases.
            allowed = (
                {"SID", "Action", "OdevID", "ShowPage", "DownloadFile", "ViewFile"}
                if path.endswith("Odevler")
                else {"ShowPage"}
                if path.endswith("Notification")
                else {"SID", "ShowPage"}
            )
            if set(query) - allowed or any(len(values) != 1 for values in query.values()):
                return False
            if any(
                not values[0].isascii() or not values[0].isdigit()
                for key, values in query.items()
                if key != "Action"
            ):
                return False
            if path.endswith("Odevler"):
                action = query.get("Action")
                if query.get("SID") is None or action not in (["List"], ["Details"]):
                    return False
                if (action == ["Details"]) != ("OdevID" in query):
                    return False
                if ("DownloadFile" in query or "ViewFile" in query) and action != ["Details"]:
                    return False
                if "DownloadFile" in query and "ViewFile" in query:
                    return False
        action_path = (
            "/pluginfile.php"
            if parsed.netloc == "uzem.altinbas.edu.tr" and path.startswith("/pluginfile.php/")
            else path
        )
        if WRITE.search(action_path) or any(
            WRITE.search(key) or key.casefold() == "sesskey" for key in query
        ):
            return False
        if any(
            value
            not in (
                {"List", "Details"} if path == "/web/Uzem/Ogrenci/Dersler/Odevler" else {"Details"}
            )
            for key, values in query.items()
            if key.casefold() == "action"
            for value in values
        ):
            return False
        if not navigation and (
            (
                STATIC.search(path)
                and (
                    path.startswith(("/asset/", "/assets/", "/lib/", "/theme/", "/pix/"))
                    or path == "/favicon.ico"
                )
            )
            or path.startswith(
                ("/theme/image.php/", "/theme/styles.php/", "/theme/javascript.php/")
            )
            or path
            in {
                "/lib/javascript.php",
                "/lib/requirejs.php",
                "/theme/styles.php",
                "/theme/yui_combo.php",
                "/web/Uzem/Picture",
                "/web/User/Picture",
            }
        ):
            return True
        if any(key.casefold() not in READ_QUERY_KEYS for key in query):
            return False
        return path in READ_PATHS[parsed.netloc] or (
            parsed.netloc == "uzem.altinbas.edu.tr" and path.startswith("/pluginfile.php/")
        )
    return not navigation and bool(STATIC.search(path))


def protect_context(context) -> None:
    context.set_default_timeout(15000)
    context.set_default_navigation_timeout(30000)
    context._readonly_blocked = []
    context._readonly_deadline = time.monotonic() + 180

    def guard(route):
        request = route.request
        if time.monotonic() >= context._readonly_deadline:
            if len(context._readonly_blocked) < 20:
                context._readonly_blocked.append(
                    {"method": "DEADLINE", "path": "scan budget expired"}
                )
            route.abort("blockedbyclient")
            return
        if request_allowed(
            request.method,
            request.url,
            navigation=request.is_navigation_request(),
            post_data=request.post_data,
        ):
            route.fallback()
        else:
            if urlparse(request.url).hostname in HOSTS and len(context._readonly_blocked) < 20:
                methods = []
                if urlparse(request.url).path == "/lib/ajax/service.php":
                    try:
                        body = json.loads(request.post_data or "[]")
                        methods = (
                            [item.get("methodname") for item in body if isinstance(item, dict)]
                            if isinstance(body, list)
                            else []
                        )
                    except ValueError:
                        pass
                context._readonly_blocked.append(
                    {
                        "method": request.method,
                        "path": urlparse(request.url).path,
                        "rpc_methods": methods,
                    }
                )
            route.abort("blockedbyclient")

    context.route("**/*", guard)

    def reject_socket(socket):
        if len(context._readonly_blocked) < 20:
            context._readonly_blocked.append(
                {"method": "WEBSOCKET", "path": urlparse(socket.url).path}
            )
        # A routed socket never reaches the network unless connect_to_server is called.
        # The installed sync driver deadlocks on close inside this callback.

    context.route_web_socket("**/*", reject_socket)


def assert_readonly(context) -> None:
    if getattr(context, "_readonly_blocked", []):
        paths = "; ".join(
            f"{item['method']} {item['path'][:100]}" for item in context._readonly_blocked[:3]
        )
        raise ActionableError(
            "READ_ONLY_REQUEST_BLOCKED: unsupported request; scan incomplete: " + paths
        )


def iter_pages(page, *, max_pages: int = 20):
    """Only explicit next-page links on the same read-only URL path are followed."""
    seen = set()
    initial = urlparse(page.url)
    for _ in range(max_pages):
        if page.url in seen:
            raise ActionableError("PAGINATION_LOOP: scan incomplete")
        seen.add(page.url)
        yield page
        next_link = page.locator(NEXT_SELECTOR)
        if not next_link.count():
            if page.locator(DYNAMIC_NEXT_SELECTOR).count():
                raise ActionableError(
                    "PAGINATION_UNSUPPORTED: dynamic next control; scan incomplete"
                )
            return
        destinations = {link.get_attribute("href") for link in next_link.all()}
        if len(destinations) != 1:
            raise ActionableError("PAGINATION_AMBIGUOUS: multiple different next destinations")
        url = urljoin(page.url, next_link.first.get_attribute("href") or "")
        parsed = urlparse(url)
        notification_alias = (
            initial.netloc == "ewi.altinbas.edu.tr"
            and initial.path == "/web/Platform/Notification"
            and parsed.path == "/web/Main"
            and set(parse_qs(parsed.query)) == {"ShowPage"}
            and len(parse_qs(parsed.query)["ShowPage"]) == 1
            and parse_qs(parsed.query)["ShowPage"][0].isdigit()
        )
        if (
            parsed.netloc != initial.netloc
            or (parsed.path != initial.path and not notification_alias)
            or not request_allowed("GET", url, navigation=True)
        ):
            raise ActionableError("PAGINATION_LINK_REJECTED")
        if url == page.url or parsed.fragment:
            raise ActionableError("PAGINATION_UNSUPPORTED: no explicit next URL")
        if notification_alias:
            url = urlunparse(parsed._replace(path=initial.path))
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if (
            notification_alias
            and not page.get_by_role("columnheader", name="Notification", exact=True).count()
        ):
            raise ActionableError(
                "PAGINATION_LAYOUT_CHANGED: EWI notification pager returned another section"
            )
    raise ActionableError("PAGINATION_LIMIT: scan incomplete")
