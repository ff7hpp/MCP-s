"""Inspect read-only submission markup without downloading files or reading inputs."""

import json
import sys

from app.lms.browser import authenticated_context
from app.storage.database import get_rows

sys.stdout.reconfigure(encoding="utf-8")
items = get_rows("assignments")
with authenticated_context() as context:
    page = context.pages[0] if context.pages else context.new_page()
    for item in items:
        if item["course_code"] not in {"MMF406", "SWE331", "SWE341"}:
            continue
        page.goto(item["url"], wait_until="domcontentloaded", timeout=30000)
        cards = page.locator(".yoo-card").filter(
            has=page.locator("h2", has_text="My Submission Files")
        )
        print(
            json.dumps(
                {
                    "course": item["course_code"],
                    "id": item["remote_id"],
                    "url": page.url,
                    "submission_text": cards.inner_text() if cards.count() == 1 else None,
                    "tables": [
                        {
                            "id": t.get_attribute("id"),
                            "text": t.inner_text(),
                            "links": t.locator("a[href]").evaluate_all(
                                "els => els.map(e => ({text:e.innerText,href:e.getAttribute('href')}))"
                            ),
                        }
                        for t in cards.locator("table").all()
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
