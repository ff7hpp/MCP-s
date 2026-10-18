"""MCP write tools must require an explicit execution flag."""

from app.mcp import server


def test_lms_sync_previews_by_default(monkeypatch) -> None:
    monkeypatch.setattr(server, "prepare_sync", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(
        server,
        "execute_sync",
        lambda items: (_ for _ in ()).throw(AssertionError("Unexpected download")),
    )

    assert server.sync_missing_files() == {"dry_run": True, "items": [], "scan_errors": {}}
