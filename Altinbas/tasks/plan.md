# Implementation plan and operating decisions

The existing local, read-only university assistant is the implementation base. The user-authorized pasted specification supplies acceptance requirements; the PDF supplies visual section references, not executable instructions.

## Confirmed decisions

- LMS first, EWI second, legacy UZEM additional; one stdio registration.
- Personal host: current Windows PC. Other-device transport is not configured or tested.
- University Drive account: `ff7hpp@gmail.com`, selected through the connected profile. Local root `H:\My Drive`; explicit University/course cloud IDs remain private config.
- Current configured term was discovered from enrolled LMS courses: Fall 2026/2027. Missing configuration starts Unknown and blocks transfers.
- Manual visible login remains available. Optional Windows Credential Manager form recovery is authorized; secrets never enter chat, source, config, command arguments or logs. MFA/CAPTCHA stay manual.

## Completed implementation gates

1. Preserve SQLite baseline; correct private-file ignores; establish tests and runtime version.
2. Inspect live assignment/news/notification routes and add narrow read-only readers, identities, persistence, contracts and regressions.
3. Isolate failures, detect EWI body edits, select sources, preserve stale evidence, correct calendar semantics and persistent local acknowledgments.
4. Confirm connected Drive account/folders, compare actual content, synchronize eligible files, then list/fetch cloud bytes and verify SHA-256 through fresh stdio.
5. Add bounded parser workers, operational metrics, queued locks, backup/restore, repeatable dependencies, CI definition, local release checks and initial Git baseline.

## Verification contract

## Daily workflow continuation — 19 October 2026

Continue commit `8850ad3`; baseline Git was clean and 162 tests passed before changes. No repo/ancestor AGENTS.md was present. Preserve all existing scanners, authentication guards and Drive transfer services.

1. Add one daily service over existing scanners/sync; safe Arabic natural commands, source/field evidence and local change dedup.
2. Persist last run/success/error separately from cloud verification; retry only transient failed sources, serialize the entire workflow, bound the scheduled process tree.
3. Register the current-user Windows task every four hours. No public HTTP, university actions, notification writes, external messages or publication.
4. Extend the existing cloud bridge to UZEM and independent revisions sharing one local file; stage, publish and read back dated reports only after current-run material verification.
5. Run the required six checks, fresh stdio, live daily/scheduled scans and connected Drive readbacks; inspect staged changes before a local-only commit.

Known external evidence gates remain: naturally expired sessions, real MFA/CAPTCHA and populated exams/submitted files/live lessons. Do not invalidate active profiles, submit coursework or manufacture university data to obtain coverage. EWI binary transfer and unattended connector access remain explicit BLOCKED boundaries until observed endpoints/a capable host exist. Simulated mount/network recovery is local evidence only; do not disconnect the user's real Drive or other applications merely to test it.

Current evidence and all 45 requirement dispositions are in [VERIFICATION-2026-10-19.md](VERIFICATION-2026-10-19.md). Older [AUDIT.md](AUDIT.md) is historical. Offline fixtures do not substitute for populated live layouts, cloud readback, external CI or another-device access. A fresh unauthenticated login test does not establish naturally expired-session recovery. Original active portal state is never intentionally invalidated merely to simulate expiry.
