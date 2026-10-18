"""Expected operational errors shown directly to MCP clients and the CLI."""

from mcp.server.mcpserver.exceptions import ToolError


class ActionableError(RuntimeError, ToolError):
    """A safe, actionable failure rather than an unexpected server crash."""
