#!/usr/bin/env python3
"""Bootstrap Jarvis secrets from 1Password into macOS Keychain.

Usage:
    python scripts/bootstrap_secrets.py
    python scripts/bootstrap_secrets.py --vault "Personal" --item "Jarvis - Entra Enterprise App"
    python scripts/bootstrap_secrets.py --verify
    python scripts/bootstrap_secrets.py --clear-tokens
"""

import argparse
import shutil
import subprocess
import sys

# Allow running from repo root
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from config import MSAL_KEYCHAIN_ACCOUNT, MSAL_KEYCHAIN_SERVICE
from vault.keychain import delete_secret, get_secret, set_secret

FIELDS = ["client_id", "tenant_id"]
SECRET_KEYS = {
    "client_id": "m365_client_id",
    "tenant_id": "m365_tenant_id",
}

DEFAULT_ITEM = "Jarvis - Entra Enterprise App"


def check_op_cli() -> bool:
    """Return True if the 1Password CLI (``op``) is available."""
    return shutil.which("op") is not None


def op_read(vault: str, item: str, field: str) -> str:
    """Read a field from 1Password via the ``op`` CLI."""
    uri = f"op://{vault}/{item}/{field}"
    result = subprocess.run(
        ["op", "read", uri],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to read '{uri}' from 1Password: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def detect_vault() -> str | None:
    """Try to auto-detect the vault containing the item."""
    result = subprocess.run(
        ["op", "vault", "list", "--format=json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    import json
    try:
        vaults = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if len(vaults) == 1:
        return vaults[0].get("name") or vaults[0].get("id")
    return None


def mask(value: str) -> str:
    """Mask a secret value for display, showing first 4 and last 4 chars."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def bootstrap(vault: str, item: str) -> None:
    """Read secrets from 1Password and store them in the Keychain."""
    for field in FIELDS:
        secret_key = SECRET_KEYS[field]
        print(f"Reading '{field}' from 1Password ({vault}/{item})...")
        value = op_read(vault, item, field)
        if not value:
            print(f"  WARNING: empty value for '{field}', skipping")
            continue
        success = set_secret(secret_key, value)
        if success:
            print(f"  Stored '{secret_key}' in Keychain ({mask(value)})")
        else:
            print(f"  FAILED to store '{secret_key}' in Keychain")
            sys.exit(1)
    print("\nBootstrap complete.")


def verify() -> None:
    """Read secrets back from the Keychain and print masked values."""
    print("Verifying Keychain secrets:\n")
    all_ok = True
    for field in FIELDS:
        secret_key = SECRET_KEYS[field]
        value = get_secret(secret_key)
        if value:
            print(f"  {secret_key}: {mask(value)}")
        else:
            print(f"  {secret_key}: NOT FOUND")
            all_ok = False
    if all_ok:
        print("\nAll secrets present.")
    else:
        print("\nSome secrets are missing.")
        sys.exit(1)


def clear_tokens() -> None:
    """Remove MSAL token cache from macOS Keychain."""
    print("Clearing MSAL token cache from Keychain...")
    try:
        result = subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-s", MSAL_KEYCHAIN_SERVICE,
                "-a", MSAL_KEYCHAIN_ACCOUNT,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("  MSAL token cache removed.")
        else:
            print("  No MSAL token cache found (may already be cleared).")
    except FileNotFoundError:
        print("  ERROR: 'security' CLI not found.")
        sys.exit(1)

    # Also offer to clear the stored credentials
    for field in FIELDS:
        secret_key = SECRET_KEYS[field]
        deleted = delete_secret(secret_key)
        if deleted:
            print(f"  Removed '{secret_key}' from Keychain.")
        else:
            print(f"  '{secret_key}' not found in Keychain (already cleared).")

    print("\nToken and credential cleanup complete. Re-run bootstrap to re-authenticate.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Jarvis secrets from 1Password into macOS Keychain",
    )
    parser.add_argument(
        "--vault",
        default=None,
        help="1Password vault name (default: auto-detect or prompt)",
    )
    parser.add_argument(
        "--item",
        default=DEFAULT_ITEM,
        help=f"1Password item name (default: '{DEFAULT_ITEM}')",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify secrets are stored in Keychain (don't write anything)",
    )
    parser.add_argument(
        "--clear-tokens",
        action="store_true",
        help="Remove MSAL token cache and credentials from Keychain",
    )
    args = parser.parse_args()

    if args.clear_tokens:
        clear_tokens()
        return

    if args.verify:
        verify()
        return

    if not check_op_cli():
        print("ERROR: 1Password CLI ('op') not found. Install it from https://1password.com/downloads/command-line/")
        sys.exit(1)

    vault = args.vault
    if vault is None:
        vault = detect_vault()
    if vault is None:
        vault = input("Enter 1Password vault name: ").strip()
        if not vault:
            print("ERROR: vault name is required")
            sys.exit(1)

    bootstrap(vault, args.item)


if __name__ == "__main__":
    main()
