# University MCP audit — 15 October 2026

## Result

The three requested file defects were reproduced before fixes. The baseline suite passed 26 tests; the final suite passes 71. The old comparator test explicitly accepted a prior-term match; that expectation was corrected. State and source were backed up before migrations; profiles and untracked work were preserved. No dependency, commit or publication was added.

| Work | Status | Evidence |
|---|---|---|
| Repeated updated-file downloads | TESTED LOCALLY | Regression initially returned UPDATED after install; now checks term/revision/SHA-256 receipt |
| Prior-term false matches | TESTED LOCALLY | Old-term file no longer PRESENT; legacy SQLite keys cannot reappear after a term transition |
| Long filename extension loss | TESTED LOCALLY | Shared sanitizer preserves extension and adds a deterministic collision suffix |
| Same-size replacements | TESTED LOCALLY | Remote identity changes and local tampering detected; explicit content verification catches unchanged-metadata replacements |
| LMS workflow | TESTED LIVE | Fresh stdio scan/preview/verify/sync/compare for SWE431; four PRESENT files; repeat performs zero transfers |
| UZEM workflow | TESTED LIVE | Manual sign-in restored session; MMF401 transfer, content verification, existing-folder relocation and repeat with zero transfers |
| Cloud placement | TESTED LIVE | Existing SWE431 and MMF401 course folders listed; nested destination files listed and PDF content read back through connected Drive |
| Combined update and diagnostics | TESTED LIVE | Fresh stdio exposes 44 tools; all three sessions authenticated; combined update returns 46 source-labelled sections |
| Freshness, conflicts, removals and notices | TESTED LOCALLY | Failed baselines preserved, scoped removals occur once, explicit time overlaps and portal differences flagged, cancellation evidence separated from confirmation |
| Populated portal layouts | TESTED LOCALLY | Offline Chromium fixtures cover resources/download links, exams, grades including blank cells, notifications and pagination |
| Read-only boundary | TESTED LOCALLY | Form/mark-read requests and mixed RPC batches blocked; two observed Moodle read RPCs explicitly allowed |
| Locking, migration, recovery and retention | TESTED LOCALLY | Cross-process lock, killed process recovery, pre-migration SQLite backup, validated recovery, corrupt-original preservation, bounded backups |
| Interrupted file install | TESTED LOCALLY | Pending receipts survive failed rename; verified destination reused; owned orphan staging removed; unrelated files retained; corrupted staging rejected |
| Syllabus and search | TESTED LIVE | Fresh stdio syllabus baseline then UNCHANGED; four text-search matches with no extraction errors |
| LMS calendars | BLOCKED | All seven live calendar widgets fail to initialize; returned as CALENDAR_UNAVAILABLE and partial coverage |
| OCR engine | BLOCKED | No OCR dependency configured; no-text PDFs are explicitly flagged. Engine work remains conditional on a real need |

Live cloud readback verified the new lecture's normalized text prefix against local extraction. UZEM readback verified the expected document title and destination parent; its original cloud file ID was preserved during relocation. Cloud bytes were not independently hashed through the connector. Remote portal bytes and local copies were hashed during sync.

## Removed duplication and dead code

- LMS and UZEM share SyncItem and execution, transfer, content validation and install paths; the second result class and download loop were removed.
- EWI and UZEM share JSON validation, durable writes, backups, change/removal comparison and locking.
- SQLite legacy-key reuse shares one helper, including the term boundary.
- Drive comparison, sync and document lookup share destination containment checks.
- EWI table pagination and table-local semester metadata are shared; notification parsing no longer scans every table twice.
- Removed the unused mixed-portal authentication helper. LMS authentication now also requires the correct host.
- README and original task notes now distinguish local delivery, connected cloud verification, fixtures and live evidence.

## Live defects found and fixed during verification

1. EWI notification pagination links pointed to `/web/Main?ShowPage=N`. Using the observed page number on the notification route returned the correct next page; pagination now validates and preserves that section. Newly visible older items from expanded pagination were not called newly posted.
2. UZEM course/content reads needed two specific POST RPCs. Arbitrary POST blocking broke those reads; the guard now allows those two method names and rejects mixed read/write calls.
3. LMS download requests needed a normal authenticated page visit before transfer. Without initialization they redirected to SSO; sync now verifies the browser session first and keeps download redirects restricted.
4. UZEM redirect handling briefly replaced the stable resource URL with the file URL. Stable resource identity is now preserved and regression tested.

## Verification commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m compileall -q app tasks/verify_stdio.py
.venv\Scripts\python.exe tasks\verify_stdio.py university_health university_update
.venv\Scripts\python.exe tasks\verify_stdio.py sync_missing_files --course-code SWE431 --execute
.venv\Scripts\python.exe tasks\verify_stdio.py uzem_sync_missing_files --course-code MMF401 --execute
.venv\Scripts\python.exe tasks\verify_stdio.py inspect_course_syllabus search_course_materials --course-code SWE431
```

Full live responses and cloud verification metadata remain under ignored `data/audit-*.json`. The source/config/state backup is under ignored `data/audit-backup-20261015-153629/`; SQLite backup integrity was checked. No browser cookies were copied into that backup.

## Exact limits and remaining risks

1. **Schedule coverage is partial.** All seven LMS calendars remain unavailable. Unknown dates/durations are retained as unknown, and conflict checks cover explicit intervals only. LMS monthly calendar disappearance is not treated as a cancellation; LMS news/dashboard disappearance is not authoritatively reconciled. EWI/UZEM successfully scanned scopes and LMS files/resources/exams support removal detection.
2. **Cloud verification requires the connected Drive step.** The standalone stdio server has no connected cloud credentials and never certifies a mount write. The orchestrated path is live-tested; fully standalone cloud verification is not implemented. Drive readback established content and parent placement, not a separate cloud-byte SHA-256.
3. **Unchanged metadata needs explicit content verification.** Use verify_content=true for a remote byte check. Normal receipt checks intentionally avoid repeated transfers and cannot discover a server replacement that preserves every exposed identifier/header/timestamp. Legacy unverified files remain UNKNOWN rather than being silently accepted.
4. **Portal parsing is bounded.** Explicit pagination is capped at 20 pages; unsupported dynamic controls fail as incomplete. Populated live exams/grades were not manufactured or changed; their parser behavior is fixture-tested. Blank grade cells remain blank. Syllabus evidence extraction is conservative, and search is bounded; image-only PDFs need an OCR engine when justified.
5. **Recovery and security tests have practical boundaries.** Process interruption, corrupted state and static symlink/junction escapes were tested locally. Destructive power-loss testing and hostile same-user processes changing directory trees between checks were not performed. Allowed read GETs may have normal server access-log effects; no form submission, mark-read action or write RPC is authorized.

Academic history and original versions are preserved. Retention limits apply to new backup generations and current alert evidence; there is no destructive purge of historical student data.


# Approved Phase 2 implementation and second audit — 16 October 2026

This section supersedes the October 15 limits where explicitly verified below. Source/config/state were backed up before changes at `data/phase2-backup-20261016-152502/`; browser profiles and cookies were not copied. SQLite migrated from version 1 to 2 with a checked migration backup. No commit, publication, new package installation or dependency-version change occurred. Pydantic, already required by the MCP SDK, is now a declared direct dependency for schemas.

## Verification dashboard

| Check | Status | Evidence |
|---|---|---|
| Full regression suite | TESTED LOCALLY | 108 passing cases; 37 additional cases versus Phase 1; final failures: zero |
| Complete-project quality checks | TESTED LOCALLY | Ruff lint and format checks pass across 64 Python files; 60 source/test/task files parse; offline wheel/source build passes; SQLite integrity is ok, schema 2 |
| P0 recovery validation | TESTED LOCALLY | Missing/wrong/malformed backups cannot replace original state; old fingerprint baselines remain readable |
| Private permissions | TESTED LOCALLY | Five private roots restricted; no unexpected Allow grants after live browsing; original ACL metadata retained |
| Read-only guard | TESTED LOCALLY | Encoded actions, unknown endpoints, forms, mark-read and mixed RPCs rejected; WebSocket network fixture receives zero requests; service workers blocked |
| Fresh MCP transport | TESTED LOCALLY | 44 tools, strict schemas, actionable safe errors; isolated scan/compare/preview/sync/lookup/repeat workflow |
| Final cached stdio checks | TESTED LOCALLY | Current SWE431 files/calendar envelopes read successfully; original Lecture3.pdf resolves verified revision; comparison returns four PRESENT. Final check exposed a legacy receipt without status; shared validation now accepts absent legacy status, rejects explicit invalid status, and preserves state without rewriting |
| Live authentication | TESTED LIVE | LMS/EWI/UZEM all authenticated through fresh stdio; UZEM restored by visible manual sign-in |
| Combined academic update | TESTED LIVE | 47 sections; 24 LMS calendar events; latest repeat has zero errors, zero changes and zero alerts |
| Calendar recovery | TESTED LIVE | Portal JavaScript SyntaxError prevented widget rendering; bounded JSON-only reader recovers explicitly serialized events without executing scripts |
| LMS sync | TESTED LIVE | SWE431 four copies remotely rehashed/adopted, original paths retained; repeat preview has four PRESENT and zero transfers |
| UZEM sync | TESTED LIVE | Announced 2026–2027 Güz category matches configuration; MMF401 existing copy remotely rehashed; repeat PRESENT with zero transfers |
| Connected Drive placement | TESTED LIVE | University/course/source/Resources/destination chains listed; file parents read back; normalized text prefixes match local extraction for both sampled PDFs |
| Newly missing live upload | BLOCKED | No new missing file was available in these scoped live runs; actual new installation is covered by isolated stdio and the dated October 15 live evidence |
| Standalone cloud certification | BLOCKED | Standalone MCP has no cloud connector bridge; tool results correctly remain pending |

Connected-cloud proof is retained narrowly in ignored `data/phase2-cloud-readback.json`; no document text is stored in that proof. Cloud bytes were not independently hashed. All five existing sampled course files were preserved; these live checks did not manufacture new uploads.

## Findings revisited

| Finding | Result | Verification / remaining limit |
|---|---|---|
| H-01 private ACLs | Fixed — TESTED LOCALLY | Repeatable native Windows DACL setup, content preservation, deny-rule preservation and bounded ACL metadata backups; existing Chromium capabilities retained |
| H-02 request guard | Fixed for audited bypasses — TESTED LOCALLY / TESTED LIVE | Observed HTTPS endpoints and asset paths; two POST read RPCs plus observed GET translation RPC; service workers blocked; WebSockets isolated; restored startup windows suppressed. Normal server-side effects of allowed GET/HEAD cannot be proven absent |
| H-03 source term | Fixed — TESTED LOCALLY / TESTED LIVE | Source semester carried through comparison and revision fingerprint; transfer rejects mismatch/unknown terms; explicit UZEM mapping only for unannounced terms |
| H-04 JSON recovery | Fixed — TESTED LOCALLY | Existing matching backup required; known state structures validated; malformed receipts rejected; original retained. Legacy completed receipts without status remain readable; strict hash/size validation still applies |
| M-01 layout/pagination | Improved — TESTED LOCALLY / TESTED LIVE | Required table headers, dated schedule cards, EWI schedule pagination, UZEM notification pagination; unsupported layouts fail. Unseen portal layouts still require validation |
| M-02 expected errors | Fixed — TESTED LOCALLY | Shared operational boundary and fresh stdio tests; validation errors identify fields without echoing input values or client tracebacks |
| M-03 schemas/annotations | Partially fixed — TESTED LOCALLY | Strict bounded inputs, unknown arguments rejected, concrete core outputs, accurate non-idempotent state annotations, database reads do not migrate. Some focused/nested outputs remain generic |
| M-04 logical filenames | Fixed — TESTED LOCALLY / TESTED LIVE | Current-term validated receipt lookup; path/hash/course containment enforced; changed active copies fail instead of selecting an old version |
| M-05 stored freshness | Fixed — TESTED LOCALLY / TESTED LIVE | Section validity/membership, last-success times, failure-preserved calendar, current announcement scope and read-only storage queries |
| M-06 resource budgets | Partially fixed — TESTED LOCALLY | Transfer and browser network budgets; size mismatch avoids unnecessary hashing. In-process PDF/Office parser CPU/memory and universal whole-tool cancellation remain unbounded |
| M-07 privacy | Fixed — TESTED LOCALLY / TESTED LIVE | Aggregate MCP scans default private-off; UZEM file preparation does not read grades; focused announcements skip file HEAD work |
| M-08 academic coverage | Improved — TESTED LOCALLY / TESTED LIVE | GLOBAL announcements included; calendar JSON restores explicit dates/times; scoped removals, reschedules and cross-portal date differences flagged. Raw exam prose and syllabus deadlines are not automatically inferred |
| L-01 noisy alerts | Fixed — TESTED LOCALLY / TESTED LIVE | Missing-scope/reappearance regression; bounded 30-day evidence memory; fresh repeat has zero alerts |
| L-02 repeated work | Partially fixed — TESTED LOCALLY / TESTED LIVE | EWI batch context and shared table reader; indexed history queries and read-only connections. JSON receipt writes still rewrite bounded local files |
| L-03 automated CI | Not implemented | Local full-project checks available; repository remains uncommitted and unpublished |
| I-01 cloud evidence | Orchestrated path TESTED LIVE | Narrow proof recorded, separate from standalone pending status; no server cloud credentials added |
| I-02 OCR / syllabus integration | Deferred | OCR engine absent; exact evidence and Unknown labels preserved; no speculative deadlines |

## Compatibility changes

The six stored tools `get_new_items`, `get_course_resources`, `get_course_files`, `get_announcements`, `get_exams`, `get_calendar_events` now return `items` plus section status, source, completeness and errors. CLI cached academic readers use the same envelope. `FRESH_AT_SCAN` refers to the reported cached timestamp. Aggregate raw MCP scans now require `include_private=true` for private results; UZEM CLI scan uses `--include-private`. Old sync receipts need a one-time content recheck because source term is now part of the revision fingerprint. A source-term mismatch cannot be bypassed with content verification.

## Consolidation and scope

- EWI guard and readers use one route registry; three table-row readers share one validated implementation.
- EWI aggregate operations share a context instead of repeatedly launching browsers.
- Receipt validation is shared by normal reads and recovery; recorded logical filenames reuse sync metadata.
- Announcement/calendar membership removals share one reconciliation helper; prior academic history is retained.
- Existing shared installer, receipt journal, operation lock and JSON persistence remain the single implementations. No broad cosmetic rewrite or replacement framework was introduced.

## Updated assessment

Engineering judgment for trusted, single-user local stdio use: Security 8/10; Architecture 8/10; Code quality 8/10; Reliability 8/10; MCP design 7.5/10; Production readiness 7.5/10. Suitable for daily supervised local use. Remaining material risks are document parser resource limits, trusted same-user processes and filesystem race windows, evolving portal layouts, scoped/unannounced schedules, and separate cloud verification. These are not claims of demonstrated exploitation.

The latest evidence flags four explicit schedule overlaps and one portal disagreement; the tool retains both sources and does not choose a winner. Review against current source scopes before changing plans.

## Files changed

- `README.md`
- `app/cli.py`
- `app/config.py`
- `app/drive/comparator.py`
- `app/drive/records.py`
- `app/drive/sync.py`
- `app/ewi/portal.py`
- `app/ewi/updates.py`
- `app/lms/browser.py`
- `app/lms/courses.py`
- `app/lms/models.py`
- `app/lms/readonly.py`
- `app/lms/scanner.py`
- `app/mcp/schemas.py`
- `app/mcp/server.py`
- `app/services/documents.py`
- `app/services/scanner.py`
- `app/services/university.py`
- `app/services/update.py`
- `app/storage/database.py`
- `app/storage/state.py`
- `app/uzem/portal.py`
- `app/uzem/sync.py`
- `app/uzem/updates.py`
- `config.example.toml`
- `pyproject.toml`
- `tasks/plan.md`
- `tasks/protect_private_state.ps1`
- `tests/test_comparator.py`
- `tests/test_database.py`
- `tests/test_file_regressions.py`
- `tests/test_populated_portals.py`
- `tests/test_reliability.py`
- `tests/test_security_boundaries.py`
- `tests/test_stdio.py`
- `tests/test_transfer.py`
- `tests/test_update.py`
- `tests/test_uzem.py`
- `uv.lock`
- `tasks/AUDIT.md` (this appended second audit)
- `tasks/todo.md` (verification status)
