"""Read course-list layout and blocked RPC names; never log tokens or input values."""

import json
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError

from app.config import UZEM_URL
from app.lms.browser import authenticated_uzem_context

sys.stdout.reconfigure(encoding="utf-8")
try:
    with authenticated_uzem_context() as context:
        page = context.new_page()

        def describe_rpc(request):
            parsed = urlparse(request.url)
            if parsed.path not in {"/lib/ajax/service.php", "/lib/ajax/service-nologin.php"}:
                return
            query = parse_qs(parsed.query)
            try:
                calls = json.loads(request.post_data or query.get("args", ["[]"])[0])
                print(
                    json.dumps(
                        {
                            "method": request.method,
                            "path": parsed.path,
                            "query_keys": list(query),
                            "info": query.get("info"),
                            "calls": [
                                {
                                    "methodname": c.get("methodname"),
                                    "argument_keys": list(c.get("args", {})),
                                }
                                for c in calls
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except (ValueError, TypeError):
                pass

        page.on("request", describe_rpc)
        page.goto(UZEM_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.locator('[data-region="course-content"]').first.wait_for(timeout=15000)
        except TimeoutError:
            pass
        print(
            json.dumps(
                {
                    "url": page.url,
                    "text": page.locator("body").inner_text()[:5000],
                    "blocked": context._readonly_blocked,
                },
                ensure_ascii=False,
            )
        )
except RuntimeError as exc:
    print(type(exc).__name__ + ": " + str(exc))
