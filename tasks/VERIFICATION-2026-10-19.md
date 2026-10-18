# Release verification — 0.2.0

Verified on 19 October 2026, Europe/Istanbul, on the existing personal Windows PC. Live timestamps are stored as UTC. This report supersedes current-status claims in the historical `AUDIT.md`; it does not rewrite past evidence. The user authorized implementation and chose `ff7hpp@gmail.com` and a personal Windows host. The PDF was inspected as a visual section reference, never treated as executable instructions.

## Daily workflow continuation — current evidence, 19 October 2026

Continued the existing clean checkout at `8850ad3`, after reading README/plan/checklist and this record. No repo/ancestor AGENTS.md was found. Baseline: 162 tests, Ruff check/format, dependency compatibility, dependency audit and offline build passed before modification. Earlier release evidence below remains dated history; **56 tools** is the current fresh-stdio count.

### TESTED LIVE

- Unified daily scan and safe content sync completed through a fresh stdio process; repeated scans emitted no duplicate important-change notification (`notify=false`). All three portals were Confirmed with zero errors. The current-user Windows Task Scheduler job then completed actual executions with `LastTaskResult=0`.
- Final scheduled run started `2026-10-18T22:49:02.840248+00:00` (19 October, 01:49 Istanbul), scanned sources by `22:50:09.045139+00:00`, and completed at `22:51:17.975558+00:00` (01:51 Istanbul). Exact per-source metrics are in private state: LMS 33,046 ms, EWI 30,313 ms, UZEM 2,828 ms. Six upcoming assignment details were retained with original links and explicit deadlines. Four possible conflicts are evidence, not proof that every portal disagreement is an error.
- **18 source-file references / 17 unique physical cloud files** are PRESENT: 17 LMS references plus one UZEM reference. LMS and UZEM share the same already-existing MMF401 bytes for one resource. Fresh connected Drive account confirmation selected `ff7hpp@gmail.com`; destination listings, folder-parent chains, exact raw fetches and SHA-256 verified every reference. No new course folder, repeated file upload or existing course-file overwrite was needed.
- Only after those current-run material receipts, `publish_daily_report` installed `University/daily-20261019-015117-974556.md`. Connected Drive then listed/fetched the exact report: **5,402 bytes**, matching SHA-256 through a fresh stdio `verify_daily_report`. Cloud verification recorded at `2026-10-18T22:52:51.406850+00:00` (01:52:51 Istanbul). Its creation-time Pending text remains unchanged; the separate receipt records later verification. A preliminary earlier report is also retained; reports have distinct run timestamps.
- **Altinbas University Daily Update** is active every **four hours**, current user/interactive logon/limited privileges. Next configured trigger after verification: **19 October 2026 05:49:01 Europe/Istanbul**. Task settings ignore overlapping instances, retry failures twice at five-minute intervals, start missed runs when available and limit execution to 20 minutes; the owned child supervisor uses 15 minutes. Registration was idempotently updated for this checkout, without a Windows password.
- Fresh stdio exposes `daily_update`, `university_request`, `daily_status`, `publish_daily_report`, `verify_daily_report`, and extended LMS/UZEM cloud bridge schemas: **56 tools**, `reconnect_required=false`. This proves the fresh process; older open MCP connections still need a reconnect to load those schemas.

### TESTED LOCALLY

- **181 tests pass**. Ruff lint, Ruff formatting, `uv pip check`, `pip_audit --local --skip-editable` and `uv build --offline` all exit **0**. Audit: no known vulnerabilities in the installed environment at verification time. No new dependency was added.
- Natural Arabic command routing, explicit sync authorization, quiet unchanged runs, stable fingerprints/local-only dedup, source-specific transient retry, retained first-attempt changes, errors notified once, Unknown failed assignment details, redacted/escaped reports, preserved last success after simulated Drive failure/recovery, and cancellation state have fixture coverage.
- Cross-process lock prevents overlapping daily scans before their run state is changed. The supervisor timeout test verifies that only its owned process tree is targeted and cancellation is recorded. Read-only POST/route guards remain covered; early MFA/CAPTCHA detection does not read the vault or submit a form. One verified login POST is allowed per attempt. A durable 15-minute reservation prevents fresh processes/scheduler retries from immediately resubmitting rejected credentials; no credentials are stored in retry state.
- Same-metadata changed remote content now appears as UPDATED even when the lower-level transfer finishes with PRESENT. An existing local file remains intact. Independent remote-revision cloud receipt keys preserve LMS and UZEM evidence for shared physical bytes; legacy receipts remain readable.
- Reports cannot be published before current-run material readbacks, cannot overwrite a different target, and cannot receive cloud success without matching connected listing/fetch identity, configured report parent, size and SHA-256. Windows PowerShell scheduler script parses successfully.
- Real config/state plus the new daily state/reports were backed up and restored into a **new ignored directory**; SQLite integrity passed. Evidence: `state-20261018T225252-5c31070b.zip`, recovery `daily-20261018T225252`. Browser profiles were not re-exported in this continuation's archive; the earlier verified profile archive is retained. Windows vault credentials remain excluded. A backup attempted during an active scan correctly returned SCAN_BUSY; retry after completion passed.

### IMPLEMENTED BUT NOT LIVE-TESTED

- A genuinely server-expired session has not occurred during these checks; all three existing sessions were live-authenticated. Earlier isolated unauthenticated-vault recovery remains earlier evidence, not natural-expiry proof.
- Actual MFA/CAPTCHA, changed real login HTML, populated exam results, submitted-file attachments and future live-lesson schedules were not induced or fabricated. Existing populated/empty/changed-layout browser fixtures remain the evidence for those branches. Real wrong passwords were not submitted.
- Network failure/retry and Drive disconnect/reconnect are simulated locally. The real Drive client was not deliberately disconnected. Supervisor hard termination is fixture-tested; an active real university browser was not killed merely to demonstrate a timeout. Immediate cancellation of every synchronous MCP browser call remains unpromised.

### BLOCKED

- **Full unattended connected-cloud verification:** Windows Task Scheduler does not possess the desktop chat's Drive connector. Scheduled scanning/local sync works; each later run remains cloud Pending until a connector-capable host performs current list/fetch/readback. No OAuth token was copied into the MCP, and no mount-only success is claimed.
- **EWI binary transfer:** 39 academic resource metadata rows were observed, including historical terms. Their existence does not establish 39 downloadable current-course files. No allowed authenticated binary endpoint was observed/enabled; EWI resources remain metadata/links until real endpoint and current-course placement evidence exist.
- Other-device access, Linux/macOS support and external CI remain outside verified deployment. No public HTTP listener, remote publication or push was performed.

Private reproduction evidence: `data/daily-final-checks.json`, `daily-final-*.log`, `daily-final-stdio.log`, `daily-cloud-provider-evidence.json`, `daily-cloud-bridge.log`, `daily-cloud-verified.json`, `daily-report-provider-evidence.json`, `daily-report-verification.json`, `daily.json`, `downloads/cloud-readbacks/daily-*.bin`. Temporary connector download URLs were not saved in these evidence files. Saved reports contain no university login credentials, cookies or tokens. Staged source/test/docs are inspected before the local-only continuation commit.

### Changed files in this continuation

- Workflow: `app/services/daily.py`, `app/cli.py`, `app/mcp/server.py`.
- Session safety: `app/lms/browser.py`, `app/lms/readonly.py`.
- Drive/recovery: `app/drive/cloud.py`, `app/storage/backup.py`.
- Operations: `tasks/run_daily.py`, `tasks/schedule_daily.ps1`, `tasks/verify_stdio.py`.
- Tests/docs: `tests/test_daily.py`, `tests/test_auto_login.py`, `tests/test_backup.py`, `tests/test_cloud_verification.py`, `tests/test_stdio.py`, `README.md`, `tasks/plan.md`, `tasks/todo.md`, `tasks/VERIFICATION-2026-10-19.md`.

## Earlier release result and proof levels

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
