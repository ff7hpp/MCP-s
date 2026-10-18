"""Optional Windows Credential Manager storage for unattended portal sign-in."""

import getpass
import json
import sys

import keyring
from keyring.errors import KeyringError

from app.errors import ActionableError

SERVICE = "altinbas-lms-mcp:auto-login"
ACCOUNT = "student"


def _require_windows_vault() -> None:
    if sys.platform != "win32":
        raise ActionableError("AUTO_LOGIN_VAULT_UNAVAILABLE: use visible manual sign-in")
    from keyring.backends.Windows import WinVaultKeyring

    if not isinstance(keyring.get_keyring(), WinVaultKeyring):
        raise ActionableError(
            "AUTO_LOGIN_VAULT_UNAVAILABLE: Windows Credential Manager is required"
        )


def saved_credentials() -> tuple[str, str] | None:
    """Return a locally stored credential without putting it in MCP results or logs."""
    if sys.platform != "win32":
        return None
    _require_windows_vault()
    try:
        raw = keyring.get_password(SERVICE, ACCOUNT)
    except KeyringError as exc:
        raise ActionableError("AUTO_LOGIN_VAULT_UNAVAILABLE: use visible manual sign-in") from exc
    if raw is None:
        return None
    try:
        item = json.loads(raw)
    except ValueError as exc:
        raise ActionableError("AUTO_LOGIN_VAULT_INVALID: reset local credentials") from exc
    if not isinstance(item, dict) or not all(
        isinstance(item.get(key), str) and item[key] for key in ("username", "password")
    ):
        raise ActionableError("AUTO_LOGIN_VAULT_INVALID: reset local credentials")
    return item["username"], item["password"]


def configure_credentials() -> None:
    """Read fresh credentials only from the local terminal, never CLI arguments."""
    _require_windows_vault()
    username = input("Student number: ").strip()
    password = getpass.getpass("New password (hidden): ")
    if not username or not password:
        raise ActionableError("AUTO_LOGIN_INPUT_EMPTY: nothing was saved")
    try:
        keyring.set_password(
            SERVICE, ACCOUNT, json.dumps({"username": username, "password": password})
        )
    except KeyringError as exc:
        raise ActionableError("AUTO_LOGIN_VAULT_UNAVAILABLE: nothing was saved") from exc


def remove_credentials() -> None:
    _require_windows_vault()
    try:
        if keyring.get_password(SERVICE, ACCOUNT) is not None:
            keyring.delete_password(SERVICE, ACCOUNT)
    except KeyringError as exc:
        raise ActionableError("AUTO_LOGIN_VAULT_UNAVAILABLE: could not remove credential") from exc
