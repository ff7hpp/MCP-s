# Release checklist — 0.2.0

- [x] Preserve baseline; correct credentials source ignore and private state exclusions.
- [x] Implement live LMS assignment, full-news, notification and catalogue reads; keep university writes blocked.
- [x] Preserve same-title identities, explicit deadlines, unknown fields, partial failures and persistent local changes.
- [x] Fix EWI body-change detection, source selection, calendar semantics and dated stale fallback.
- [x] Confirm selected connected Drive account and all seven course folders; verify all 17 resource files by cloud readback hashes.
- [x] Make CLI/MCP sync preview first; require known matching terms; ignore other-root receipts.
- [x] Add optional-auth diagnostics, runtime fingerprints, queued locks and source/storage metrics.
- [x] Isolate parsers; test malformed/large/time-limited documents and Windows memory enforcement.
- [x] Restore real state/profile archive into a separate directory; SQLite integrity passed.
- [x] Define Windows CI; run local tests, lint/format, dependency audit, packaging and fresh stdio checks.

## Evidence-dependent follow-ups

- [ ] Observe a naturally expired university session and recovery; fresh unauthenticated login is already live-tested.
- [ ] Validate populated live exam, submitted-file and live-lesson layouts when the portal supplies them.
- [ ] Configure/test authenticated access from a second device if requested; current deployment remains personal Windows stdio.
- [ ] Run GitHub Actions after an explicitly authorized remote publication. No remote is configured.

No Linux/macOS compatibility, migrated browser authentication, OCR or immediate whole-browser cancellation is claimed. See [VERIFICATION-2026-10-19.md](VERIFICATION-2026-10-19.md) for precise boundaries.
