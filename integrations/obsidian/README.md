# Obsidian MCP for AI-MIND

This integration uses the upstream [Obsidian MCP Connector](https://github.com/istefox/obsidian-mcp-connector). The connector runs inside Obsidian and exposes the open vault through a local MCP endpoint. It is separate from this repository's Altinbas Python MCP server.

## Requirements and setup

1. Open the intended vault in Obsidian. In **Settings → Community plugins**, turn **Restricted mode** off and install/enable **MCP Connector** by `istefox`.
2. In the connector settings, create a Codex client token and copy its local MCP URL. The URL contains a vault-specific route ID; the bearer token is a separate secret. Keep both out of Git, screenshots, and shared logs.
3. In PowerShell, set a persistent *user* environment variable with the token locally. Replace the placeholder with the token copied from Obsidian. Do not paste the real token into a repository file or chat.

   ```powershell
   [Environment]::SetEnvironmentVariable('OBSIDIAN_AI_MIND_MCP_TOKEN', '<token from Obsidian>', 'User')
   ```

4. Register the server with Codex, replacing the placeholder URL with the one shown by the connector. Use the same environment variable name:

   ```powershell
   codex mcp add obsidian_ai_mind --url 'http://127.0.0.1:27200/v1/<route-id>/mcp' --bearer-token-env-var OBSIDIAN_AI_MIND_MCP_TOKEN
   ```

5. Restart Codex so the new user environment variable and MCP registration are loaded. Keep Obsidian and the vault open while using its tools.

On the machine where this integration was first configured, the registration name is `obsidian_ai_mind`. Its token and actual route ID are intentionally absent from this repository. The Obsidian plugin's `data.json` is local runtime state and must never be committed.

## Verify

```powershell
codex mcp get obsidian_ai_mind
```

Confirm the entry has a loopback URL and `OBSIDIAN_AI_MIND_MCP_TOKEN` as its bearer token environment variable. In a fresh Codex session with Obsidian open, ask Codex to list Obsidian MCP tools and perform a read-only vault lookup. Successful registration alone does not prove the plugin is running or that a vault request succeeds. The original AI-MIND setup returned server status `ok` and exposed 64 tools, including `search_vault_smart`; those numbers are observations from that setup, not a guarantee for future versions.

## Stop or remove

- Stop access temporarily by closing Obsidian or disabling the connector in its Community plugins settings.
- Remove the Codex registration with `codex mcp remove obsidian_ai_mind`.
- If no longer needed, clear the saved user token locally:

  ```powershell
  [Environment]::SetEnvironmentVariable('OBSIDIAN_AI_MIND_MCP_TOKEN', $null, 'User')
  ```

Removing the Codex entry does not uninstall the Obsidian plugin or alter vault notes. If the token may have leaked, revoke/rotate it in the connector settings before reconnecting.
