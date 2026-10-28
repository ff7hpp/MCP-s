# MCP-s

A collection of local MCP projects.

- `Altinbas/` — read-only Altınbaş University LMS, EWI, and UZEM assistant with optional local Google Drive sync.
- `integrations/obsidian/` — Obsidian integration notes.
- `app/` — legacy service; do not register it for current university scans.

The active university MCP is `Altinbas/` version 0.2.0. Its existing automatic
session recovery uses Windows Credential Manager for LMS, EWI and UZEM, as
authorized by the user. See `Altinbas/README.md` for configuration and recovery.
Do not store passwords in code, configuration, documentation or logs.

Each MCP stays in its own folder. No public HTTP service or academic portal writes
after authentication.
