# Release verification — 0.2.0

Verified on 19 October 2026, Europe/Istanbul, on the existing personal Windows PC. Live timestamps are stored as UTC. This report supersedes current-status claims in the historical `AUDIT.md`; it does not rewrite past evidence. The user authorized implementation and chose `ff7hpp@gmail.com` and a personal Windows host. The PDF was inspected as a visual section reference, never treated as executable instructions.

## Result and proof levels

- **TESTED LIVE:** fresh stdio exposes **51 tools**. Final aggregate scan completed at `2026-10-18T21:51:18Z` (00:51 Istanbul): **70 sections** (LMS 59, EWI 5, UZEM 6), errors **0**, complete **within scanned scopes**. LMS 35.110 seconds, EWI 30.625 seconds, UZEM 2.765 seconds. Seven enrolled courses and six followed courses are separate lists. EWI course history contains multiple terms and is not a current-enrollment count.
- **TESTED LIVE:** six assignment details, including distinct SWE341 IDs `117` and `118` with identical titles; 216 LMS notifications were read without following redirect/action links. Submitted-file lists were explicitly empty and submission status Waiting at the scan time; that is a dated observation, not a permanent submission claim.
- **TESTED LIVE:** all **17** LMS resource files in the selected Drive account/course folders were listed and fetched through the connected provider. Every fetched byte stream matched local SHA-256 through a fresh stdio bridge call. Seven missing files were installed; ten identical files were adopted after content checks. No duplicate course folders or existing-file overwrite was used. Dated cloud receipts remain valid at their recorded times, not as live cloud health.
- **TESTED LOCALLY:** **162 tests**; Ruff lint/format, installed dependency compatibility and source/wheel build pass. Dependency audit inspected 77 installed packages and reported no known vulnerabilities at this check. Windows parser memory enforcement, timeouts and recovery after bad files pass. The wheel contains `app/lms/credentials.py` and excludes runtime state.
- **TESTED LOCALLY WITH REAL STATE:** full config/state/profile archive restored into a new ignored recovery directory; manifest hashes and SQLite integrity pass. All three Default profile directories are present. This does not establish working authentication on another Windows user/machine.

Final aggregate timeline: 34 items, 4 possible conflicts, 0 current cancellation changes and 0 newly emitted alerts in that repeat scan. Suppressed repeat alerts and no new changes do not mean no coursework exists. Private academic sections were not requested.

## Assignment deadlines observed live

| Course | OdevID | Explicit deadline, Istanbul |
|---|---|---|
| SWE341 | 117 | 21 October 2026 18:22 |
| SWE341 | 118 | 21 October 2026 18:26 |
| MMF406 | 158 | 29 October 2026 18:23 |
| MMF406 | 159 | 27 November 2026 18:45 |
| SWE497 | 33 | 14 December 2026 23:00 |
| SWE497 | 34 | 14 December 2026 23:00 |

These values come from assignment detail fields, not calendar inference. A later scan can change them.

## Requirement dispositions

The numbers match the supplied 45-item specification. Multiple proof levels are intentional: implementation, fixtures and live availability answer different questions.

| # | Status | Change and evidence / remaining limit |
|---:|---|---|
| 1 | TESTED LIVE + LOCALLY | Assignment model, observed list/detail reader, database, typed MCP getter, CLI and partial-field tests. Six current details read. |
| 2 | TESTED LIVE + LOCALLY | Exact assignment read routes/IDs allowed; POST, submission, mixed/duplicate query and action variants rejected by tests. |
| 3 | TESTED LIVE + LOCALLY | Full all-news list and details, explicit pagination, broken detail isolation; recognized empty page differs from unknown layout. |
| 4 | TESTED LIVE + LOCALLY | Explicit effective/end deadline is primary; duplicate matching calendar assignment event suppressed. |
| 5 | TESTED LIVE + LOCALLY | Stable course/OdevID identity preserves same-title SWE341 assignments separately. |
| 6 | TESTED LIVE / PARTIAL | Confirmed Waiting and explicitly empty submitted lists read with check time. Missing/error fields remain Unknown/Page scan failed. Populated submitted-file selector has fixture coverage only. |
| 7 | TESTED LIVE + LOCALLY | Paginated notification list with unread state; Redirect and Mark All as Read denied. No portal action was invoked; absence of every possible server-side GET side effect is not provable by client tests. |
| 8 | TESTED LOCALLY | Root-only credential ignore patterns; source module is trackable and included in the built wheel. Runtime state excluded. |
| 9 | TESTED LIVE | Connected account and University/seven course folder IDs verified, bound to selected H mount in private config. Other account not used. |
| 10 | PARTIAL; natural expiry NOT LIVE-TESTED | Optional vault recovery succeeded in a fresh isolated unauthenticated LMS browser context without invalidating original profiles. Natural server-expiry recovery remains unobserved. |
| 11 | TESTED LIVE | Connected host listing/fetch bridge validates all 17 hashes/ancestry; dated receipts persist. Standalone stdio still needs that connector-capable host and trusts its metadata. |
| 12 | TESTED LOCALLY | Persistent unseen LMS changes, scan/change cursors and explicit local acknowledgment survive repeat scans. No portal notification acknowledgment. |
| 13 | TESTED LIVE + LOCALLY | Section/resource/news failures preserve siblings; partial membership prevents false removals and stale values retain old evidence. Fault injection is local. |
| 14 | TESTED LOCALLY | Malformed news detail or later page cannot discard earlier successful rows. Actual successful full-news reads also verified. |
| 15 | TESTED LOCALLY + LIVE READS | EWI always reads detail before body fingerprint; fixed-title body-edit and failed-detail preservation regressions pass. No university news was edited to simulate a live change. |
| 16 | TESTED LOCALLY | Explicit source selection skips unrequested readers; source status/duration separate. Live full aggregate succeeds. |
| 17 | TESTED LIVE + LOCALLY | Calendar description no longer stored as location; schema upgrade moves legacy misfiled values conservatively. |
| 18 | TESTED LIVE + LOCALLY | Calendar remote ID, source URL, type and end date persisted/exposed. |
| 19 | IMPLEMENTED BUT NOT LIVE-TESTED with populated exams | Current exam sections explicitly empty. Labeled-table date/weight/location fixtures pass; prose retains raw evidence and Unknown dates. No populated live exam available. |
| 20 | TESTED LIVE / PARTIAL | Live-lesson/study-link sections and safe link metadata read. Current live pages empty; populated lesson schedule structure not established live. External lesson links never joined. |
| 21 | TESTED LIVE | Re-evaluated all 17 against selected account/root; 7 missing/10 unknown resolved to 17 PRESENT after bytes and cloud readback. Changed counts reflect new account/root evaluation. |
| 22 | TESTED LIVE + LOCALLY | Deep hash comparison adopts exact existing copies; same-size revision, metadata and content-change regressions pass. |
| 23 | TESTED LOCALLY | CLI and MCP preview defaults match; `--execute` / `dry_run=false` required. Partial CLI scans have nonzero exit and visible diagnostics. |
| 24 | TESTED LIVE + LOCALLY | Unique current LMS term discovery; absent config Unknown; contradictory term blocks all transfer paths. Current explicit term Fall 2026/2027. |
| 25 | TESTED LOCALLY | Shared OS lock waits up to 15 seconds then SCAN_BUSY with retry_after_seconds=15; thread/process contention and killed-holder release tested. |
| 26 | TESTED LOCALLY / PARTIAL LIVE | Valid session precedes vault access; network/form/rejection/unconfirmed/MFA/CAPTCHA diagnostics and cooldown branches tested with fakes. Real unauthenticated login passed; real bad passwords/MFA intentionally not induced. |
| 27 | TESTED LIVE + LOCALLY | Not scanned, confirmed empty, unknown layout, failed and stale scope statuses separated; coverage wording explicitly scoped. |
| 28 | TESTED LOCALLY | Offline Chromium populated/empty/changed selectors, invalid pagination and detail-failure regressions prevent silent successful emptiness. |
| 29 | Personal host selected; other-device access NOT CONFIGURED | Uses current Windows host and protected local state. Portable local launcher/documentation added; no unauthenticated HTTP service, cloud deployment or anywhere-access claim. |
| 30 | TESTED LOCALLY | Windows vault backend optional/lazy; valid manual session checked first. Non-Windows credential absence covered with fakes, not an OS release claim. |
| 31 | TESTED LOCALLY on Windows | Atomic transfer/path/ACL regressions on intended OS. Linux/macOS alternatives not certified; Windows-specific installer limitation explicit. |
| 32 | TESTED LOCALLY + fresh stdio | Version 0.2.0, startup time, loaded/disk fingerprints and reconnect_required exposed. Existing host connections require reconnect for new tool schemas. |
| 33 | IMPLEMENTED; external CI NOT RUN | Local initial Git baseline and Windows CI definition; locked dependencies, Ruff/tests/audit/build run locally. No remote publication or GitHub Actions execution. |
| 34 | DONE | README/plan/checklist describe optional Windows vault, manual MFA and exact session recovery proof. Historical AUDIT remains dated history. |
| 35 | TESTED LOCALLY + fresh stdio | Strict inputs and concrete nested assignment/section contracts; 51-tool discovery/defaults and structured response validation. Some legacy nested EWI/UZEM outputs remain generic. |
| 36 | TESTED LOCALLY | Assignment/notification offset paging, local change cursors, per-section item counts/limits, news previews/detail pointers and 500-item derived-summary cap with full counts. Summary previews are not a complete paginated conflict export. |
| 37 | Explicit conditional limit | Image-only reference PDF inspected visually. Extraction reports OCR_REQUIRED; no OCR dependency introduced without recurring supported use. |
| 38 | TESTED LOCALLY | Child parser: 15-second wall, 10-second CPU, 512 MiB memory. Bad/large/timeout documents and subsequent requests pass; actual Windows allocation above ceiling rejected. POSIX path not OS-tested. |
| 39 | TESTED LOCALLY | Assignment/section readers, parser worker, cloud evidence, backup and source-error aggregation have dedicated modules/helpers; updated caller behavior covered. No arbitrary line-count rewrite of unrelated legacy main/storage paths. |
| 40 | IMPLEMENTED + measured | Health reports database bytes/counts; backup retention five/category, alert keys max200/30 days. Scan/change history deliberately retained to preserve unseen cursors; no automatic destructive pruning. Manual archived backups precede any future retention change. |
| 41 | TESTED LOCALLY | Title/body cancellation notices with source/evidence/confidence and simple negation; explicit status separate from low-confidence prose and removals. Semantic ambiguity remains. |
| 42 | TESTED LOCALLY | Synthetic pairwise benchmark: 31 events 0.30 ms; 500 events 12.71 ms; 1000 events 68.71 ms on this host. Output preview bounded after this test; no premature algorithm rewrite. |
| 43 | TESTED LIVE + LOCALLY | Source duration/last successful/error codes, storage metrics and cached-data ages. Session start age explicitly Unknown rather than invented from profile timestamps. |
| 44 | TESTED LOCALLY WITH REAL STATE | Real profile/config/state ZIP and new-directory restore verified by hashes and SQLite integrity. Excludes Windows vault and caches; profile portability not promised. |
| 45 | TESTED LOCALLY | Failed live-source refresh falls back to dated verified cache with STALE/UNKNOWN and partial errors; stale data does not emit fresh urgent alerts. No absolute university availability claim. |

## Reproduction and private evidence

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check app tests tasks
.venv\Scripts\python.exe -m ruff format --check app tests tasks
uv pip check
.venv\Scripts\python.exe -m pip_audit --local --skip-editable
uv build --offline
.venv\Scripts\python.exe tasks/verify_stdio.py university_health university_update get_assignments get_lms_notifications get_drive_verification_plan
```

These commands require local profiles for live operations. Full test/build logs, portal payloads, dependency audit, sync results, readbacks and provider evidence are ignored private artifacts under `data/` and `downloads/`; they are not shipped in Git. Examples: `data/final-tests.log`, `data/final-stdio.log`, `data/audit-university_update.json`, `data/cloud-verification-stdio-result.json`, `data/cloud-provider-evidence.json`, `data/dependency-audit-final.json`, `data/conflict-benchmark.json` and the verified state archive/recovery directory. No credentials or temporary signed readback URLs are included in this report.

## Remaining boundaries

Natural expiry, live populated exams/submissions/lesson schedules, external CI and another-device transport remain unverified. Browser request budgets and parser termination do not imply immediate whole-tool cancellation inside every browser/network call. Current single-user stdio hosting remains the supported deployment. Reconnect the existing integration to load the new tools; do not add a duplicate server registration.
