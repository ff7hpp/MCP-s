# Altınbaş University MCP

Read-only LMS, EWI and legacy UZEM assistant. Version **0.2.0**, Python 3.12, one personal Windows stdio host. The current verification record is [tasks/VERIFICATION-2026-10-19.md](tasks/VERIFICATION-2026-10-19.md); older audit reports describe earlier releases.

## Start here

```powershell
uv sync --locked --extra dev --python 3.12
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) 'browser-binaries'
.venv\Scripts\python.exe -m playwright install chromium
.\tasks\protect_private_state.ps1
.venv\Scripts\python.exe -m app.cli configure-drive
.venv\Scripts\python.exe -m app.cli login
.venv\Scripts\python.exe -m app.cli ewi-login
.venv\Scripts\python.exe -m app.cli uzem-login
.venv\Scripts\python.exe -m app.cli configure-term
```

Manual sign-in uses the visible browser. `configure-term` discovers a unique academic term from enrolled LMS courses or accepts an explicit term; an absent configuration starts as `Unknown`, which blocks file transfers. Contradictory portal semesters also block transfer. Optional UZEM course-ID mappings cannot override an announced contradictory term.

Keep the existing `altinbas-lms` registration; all portals share it. `codex mcp get altinbas-lms` shows the configured command. [tasks/start_mcp.ps1](tasks/start_mcp.ps1) resolves this checkout and launches its virtual environment. The registration example is [.codex/config.example.toml](.codex/config.example.toml). Reconnect the MCP integration after changes; an already running process keeps its loaded code and tool schemas. `lms_status` and `university_health` report version, process start, loaded/disk source fingerprints and `reconnect_required`.

The chosen deployment is the **current personal Windows PC**, using its own protected profiles, SQLite and Windows vault. It must be available when queried. Access from a second device is **not configured or live-tested**. A separately configured authenticated SSH stdio connection or remote desktop can use this host; copying a profile does not establish remote access. This project opens no network MCP listener. Linux/macOS installation and Windows profile portability are not release claims.

## Daily tools

1. `university_health` checks current portal sessions, configured term, mount availability, storage and source metrics. A profile directory does not prove authentication; mount availability does not prove cloud health.
2. `university_update(sources=["LMS"])` refreshes LMS only. Omit `sources` for LMS, EWI and UZEM. Unrequested sources say `Not scanned`. Private grades, attendance and transcript require `include_private=true`.
3. `get_assignments` reads cached assignment details. `get_lms_notifications` reads cached notifications; `get_course_links` returns live-lesson/study-link metadata. Refresh first. `get_lms_catalogue` reads the followed catalogue separately from enrolled courses, with explicit page/search controls.
4. `get_new_items` returns persistent unseen LMS changes. Use `after_change_id`, `since_scan_id` and `limit` to page. Only explicit `acknowledge_new_items(through_change_id=...)` consumes reviewed changes locally; it never marks university notifications read.
5. Sync previews by default in both MCP and CLI. Execute authorized sync explicitly; then complete connected Drive verification below.

```powershell
.venv\Scripts\python.exe -m app.cli university-health
.venv\Scripts\python.exe -m app.cli university-update --sources LMS --json
.venv\Scripts\python.exe -m app.cli assignments --json
.venv\Scripts\python.exe -m app.cli notifications --json
.venv\Scripts\python.exe -m app.cli sync SWE431 --json
.venv\Scripts\python.exe -m app.cli sync SWE431 --execute --verify-content --json
.venv\Scripts\python.exe -m app.cli uzem-sync --course-code MMF401 --execute --verify-content
```

## Assignment and source evidence

Assignments use course identity plus `OdevID`; duplicate titles remain distinct. Records include start/end, explicit effective deadline, instructions by language, attachments, submission status, submitted files, field status, source URL and check time. `due_at` comes from the assignment detail page, with Istanbul timezone, taking precedence over matching calendar entries. Calendar records separately retain remote ID, description, location, source, type and end date. Unknown dates and durations are never inferred from prose.

`null` means `Unknown`. A confirmed empty files list is different from an unavailable files list. A detail failure has `detail_error` and `Page scan failed`; it never proves that no assignment exists or nothing was submitted. Explicit empty exam/lesson pages mean no announced data in that scope. Unknown layouts report a failure or preserve unstructured evidence instead of claiming structured fields.

Scans isolate resource/news/detail failures, retain successful siblings and report partial scope. Failed refreshes preserve previous verified values and timestamps, marked `STALE` or `UNKNOWN`; stale values do not create fresh urgent alerts. Successful complete scopes alone establish removals. A removal is not proof of cancellation. Cancellation notices inspect title and body, carry source/evidence and conservative confidence, and handle simple negation; prose classification still needs judgment. EWI news fingerprints include detail content even when title/link are unchanged.

Stored results are envelopes: `items`, `sections`, completeness, errors and source/freshness metadata. `get_assignments` and `get_lms_notifications` accept `offset` and `limit` (1..500) and return `total_items`, `has_more`, `next_offset`. Aggregate sections default to 100 items, configurable through `max_items_per_section` (1..500); `item_count` and `has_more` disclose omitted rows. Long news bodies become 2,000-character previews with a detail tool. Derived summary lists are capped at 500 each with `summary_counts`, `summary_limit` and `response_has_more`. These are previews; use focused source tools or source URLs for complete evidence. Full analysis precedes preview truncation.

First EWI/UZEM scans establish baselines; later `NEW` means newly observed, not necessarily newly posted. Timetables/calendar coverage is limited to displayed dates or explicit embedded payloads. Portal disagreements are possible disagreements, not automatic proof of an error. Pairwise conflict analysis requires explicit intervals; unknown duration is not guessed.

## Drive correctness

Destination account and folder IDs belong in ignored `config.toml`, after connected account/folder confirmation. Root changes preserve the explicit mapping and ignore receipts belonging to other mounted roots. Current-term transfers use the unique existing University course folder; absent or ambiguous folders block sync. No second course folder is created during a transfer.

Names, rounded sizes and unversioned old copies do not prove identity. Receipts bind portal/source, term, remote ID/revision and local SHA-256. `verify_content=true` downloads and compares actual bytes, adopts identical existing files, and retains a distinct revision if content differs. Unknown identity is never silently treated as missing. Deterministic revision names and pending receipts make retries resumable. Symlinks/junctions, path escape and overwrite are rejected. Downloads validate every redirect, identifiers, names, file signatures, archive structure and a 25 MiB ceiling. Transfer budget is 120 seconds between reads, with up to a 30-second active socket read timeout.

The standalone stdio process has no connected Drive OAuth capability. After sync, its host must:

1. Read `get_drive_verification_plan` and use the bound connected account and University/course folder IDs.
2. List the destination and ancestry, then fetch the exact cloud file through the Drive connector. Do not upload a duplicate if Drive for Desktop already delivered it.
3. Materialize fetched bytes under ignored `downloads/cloud-readbacks/` and call `verify_drive_readback` with connector evidence and the readback filename.

The bridge validates account/IDs/ancestry/size/SHA-256 against local bytes and records `VERIFIED_AT_RECORDED_TIME`. It trusts the desktop host's connector metadata; it is not an independent OAuth or live cloud query. Local/source changes invalidate its applicability. Without that bridge, status remains `PENDING_CONNECTOR_LIST_AND_READBACK`. `university_health` deliberately reports cloud health as not checked. A dated file receipt is not continuous cloud availability.

## Authentication and read-only boundaries

`auto-login-setup` optionally prompts **locally** and stores credentials in Windows Credential Manager; no password belongs in chat, command arguments, source, config or logs. `auto-login-remove` removes the stored entry. A valid manual session is checked before importing/querying the optional Windows credential backend. On an unauthenticated session, one bounded form attempt may restore access; failed attempts pause retries in that process for 15 minutes. Network failure, changed form, rejected credentials, unconfirmed sign-in and MFA/CAPTCHA have distinct diagnostics. MFA/CAPTCHA require visible manual action. Same-user Windows programs and administrators remain trusted.

After authentication, the guard allows observed HTTPS read routes only. Assignment reads permit exact validated `Action=List/Details`, `SID`, `OdevID` and observed file/page parameters. All-news lists are paginated. LMS notifications never follow their `Redirect` links or mark-read actions; catalogue reads never activate follow controls. Passive EWI article images allow only the observed non-navigation `GetImage` request with numeric `NewsID` and `FileID`.

UZEM permits only its two observed POST read RPCs and GET translation RPC; mixed write/read batches fail. Service workers and routed WebSockets cannot connect. Unrecognized pagination fails the scope while retaining already read rows. Normal server access logs can still occur on a GET; client guards do not prove every server implementation detail. Portal/document text is untrusted data, never instructions. Forum posts, uploads, submissions, registrations, payments and messages are never executed by a scan.

## Local state and recovery

Private config, profiles, cookies, downloads, scan outputs, backups and databases are ignored by Git. Run `protect_private_state.ps1` before sign-in and after moving the project; it restricts sensitive directories to the current Windows user, SYSTEM and Administrators. MCP arguments/results enter the host conversation, so private reads remain explicit.

One OS operation lock serializes profile/state/transfer access. Shared operations wait up to 15 seconds, then return `SCAN_BUSY` with `retry_after_seconds=15`. The OS releases the lock when a process ends. Browser contexts have a 180-second network budget; that does not promise immediate cancellation inside every browser call.

SQLite schema **3** retains academic items, explicit calendar fields and partial/complete membership. Migration makes an integrity-checked database backup and rejects newer schemas. JSON state uses flush/fsync and atomic replacement. Five backup generations are retained per state file/archive category; alerts keep at most 200 keys for 30 days. Scan/change history, browser profiles and original document versions are retained rather than automatically purged. `university_health` reports database bytes and row counts so a deliberate archive can precede deletion without destroying unseen-change cursors.

```powershell
.venv\Scripts\python.exe -m app.cli backup-state --profiles
.venv\Scripts\python.exe -m app.cli restore-check '<archive path printed above>'
```

Archives contain config, selected state and optional dedicated browser profiles, excluding browser caches and Windows vault credentials. They are private session-bearing artifacts. A SQLite online backup, checksums, 500 MiB/10,000-file ceilings and path validation protect creation/restore. Restore-check writes only a **new** ignored recovery directory and checks SQLite integrity; it never replaces active state. Browser cookies may depend on the original Windows user/machine; integrity-tested restore does not prove migrated authentication. Older single-file `recover-state` remains available after closing SQLite clients/checkpointing WAL.

Document extraction runs in a separate process: 15-second wall timeout, 10-second CPU and 512 MiB memory limits (Windows Job Object; POSIX path not verified). Malformed/large/time-limited requests do not end the MCP server. PDF/PPTX/DOCX/TXT/MD are supported. `inspect_course_syllabus` and `search_course_materials` return source excerpts/hashes; extraction lines are not PDF page numbers. Search is limited to 30 files and 100,000 characters per file. Image-only PDFs report `OCR_REQUIRED`; OCR was not added without a demonstrated recurring extraction need.

## Verification and release

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check app tests tasks
.venv\Scripts\python.exe -m ruff format --check app tests tasks
uv pip check
.venv\Scripts\python.exe -m pip_audit --local --skip-editable
uv build --offline
.venv\Scripts\python.exe tasks/verify_stdio.py university_health university_update
```

`tasks/verify_stdio.py` launches a fresh server, checks tool defaults and writes private responses under ignored `data/audit-*.json`. It supports explicit sync execution/content checks. Windows CI is defined in [.github/workflows/ci.yml](.github/workflows/ci.yml), with locked dependencies, browser fixtures, lint, tests, dependency audit and build. A local run does not prove an external GitHub Actions run. Release evidence separates **TESTED LIVE**, **TESTED LOCALLY**, **IMPLEMENTED BUT NOT LIVE-TESTED** and **BLOCKED**.
