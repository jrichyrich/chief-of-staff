# Graph Token Lifecycle Improvements

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Graph API token lifecycle: structured 1Password fields, `client_secret` in bootstrap, `--reauth` command, actionable notification messages.

**Architecture:** Extend `scripts/bootstrap_secrets.py` with `client_secret` field support and a `--reauth` flag that runs MSAL device code flow directly. Update notification messages in `mcp_server.py` and `scheduler/daemon.py` to reference `--reauth`. Update the 1Password item to use structured fields so `op read` works.

**Tech Stack:** Python, MSAL, macOS Keychain (`security` CLI), 1Password CLI (`op`), osascript notifications

---

## Pre-Flight: Structure the 1Password Item

Before any code changes, the 1Password item needs structured fields so `op read` can pull individual values.

**Step 1: Update 1Password item with structured fields**

Run these commands to add structured fields to the existing item (using the Employee vault copy):

```bash
# Add structured fields from the current notes values
op item edit l5evwwyz3z4dwl7nnh5q7u7y5a \
  "client_id=<YOUR_CLIENT_ID>" \
  "tenant_id=<YOUR_TENANT_ID>" \
  "client_secret[password]=<YOUR_CLIENT_SECRET>"
```

**Step 2: Verify the fields are readable**

```bash
op read "op://Employee/Jarvis - Entra Enterprise App/client_id"
op read "op://Employee/Jarvis - Entra Enterprise App/tenant_id"
op read "op://Employee/Jarvis - Entra Enterprise App/client_secret"
```

Expected: Each prints the correct value.

---

### Task 1: Add `client_secret` to bootstrap

**Files:**
- Modify: `scripts/bootstrap_secrets.py:22-26`

**Step 1: Update FIELDS and SECRET_KEYS**

Replace lines 22-26:

```python
FIELDS = ["client_id", "tenant_id", "client_secret"]
SECRET_KEYS = {
    "client_id": "m365_client_id",
    "tenant_id": "m365_tenant_id",
    "client_secret": "m365_client_secret",
}
```

**Step 2: Update `verify()` to check all 3 keys**

No code change needed — `verify()` already iterates `FIELDS`/`SECRET_KEYS`, so adding `client_secret` to those dicts is sufficient.

**Step 3: Verify `--clear-tokens` covers `client_secret`**

No code change needed — `clear_tokens()` iterates `FIELDS` on line 137, so `client_secret` will be included automatically.

**Step 4: Test**

```bash
python scripts/bootstrap_secrets.py --verify
```

Expected: All 3 secrets shown (client_id, tenant_id, client_secret).

**Step 5: Commit**

```bash
git add scripts/bootstrap_secrets.py
git commit -m "feat: add client_secret to bootstrap_secrets FIELDS"
```

---

### Task 2: Add `--reauth` command

**Files:**
- Modify: `scripts/bootstrap_secrets.py`

**Step 1: Add the `reauth()` function after `clear_tokens()`**

Add after line 145 (after `clear_tokens` function):

```python
def reauth() -> None:
    """Run interactive device code flow to refresh the MSAL token cache."""
    try:
        import asyncio
        from config import M365_CLIENT_ID, M365_GRAPH_SCOPES, M365_TENANT_ID
        from connectors.graph_client import GraphClient
    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}")
        print("Run: pip install -e '.[dev]'")
        sys.exit(1)

    if not M365_CLIENT_ID:
        print("ERROR: m365_client_id not found in Keychain or environment.")
        print("Run: python scripts/bootstrap_secrets.py  (to bootstrap from 1Password first)")
        sys.exit(1)

    print("Starting interactive Graph API re-authentication...")
    print("A browser window will open for you to sign in.\n")

    gc = GraphClient(
        client_id=M365_CLIENT_ID,
        tenant_id=M365_TENANT_ID,
        scopes=M365_GRAPH_SCOPES,
        interactive=True,
    )
    try:
        token = asyncio.run(gc.ensure_authenticated())
        if token:
            print("\nRe-authentication successful. Token cached in Keychain.")
        else:
            print("\nRe-authentication failed.")
            sys.exit(1)
    except Exception as e:
        print(f"\nRe-authentication failed: {e}")
        sys.exit(1)
    finally:
        asyncio.run(gc.close())
```

**Step 2: Add `--reauth` argument to argparse**

In `main()`, after the `--clear-tokens` argument (after line 174), add:

```python
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Re-authenticate interactively (device code flow) to refresh tokens",
    )
```

**Step 3: Add the reauth dispatch in `main()`**

After the `clear_tokens` dispatch block (after line 176), add:

```python
    if args.reauth:
        reauth()
        return
```

**Step 4: Update docstring**

Update the module docstring at top of file to include the new command:

```python
"""Bootstrap Jarvis secrets from 1Password into macOS Keychain.

Usage:
    python scripts/bootstrap_secrets.py
    python scripts/bootstrap_secrets.py --vault "Personal" --item "Jarvis - Entra Enterprise App"
    python scripts/bootstrap_secrets.py --verify
    python scripts/bootstrap_secrets.py --clear-tokens
    python scripts/bootstrap_secrets.py --reauth
"""
```

**Step 5: Test help output**

```bash
python scripts/bootstrap_secrets.py --help
```

Expected: Shows `--reauth` option in help text.

**Step 6: Commit**

```bash
git add scripts/bootstrap_secrets.py
git commit -m "feat: add --reauth to bootstrap_secrets for interactive token refresh"
```

---

### Task 3: Update notification messages to reference `--reauth`

**Files:**
- Modify: `mcp_server.py:229-236`
- Modify: `scheduler/daemon.py:108-117`
- Modify: `connectors/graph_client.py:276-281`

**Step 3a: Update `mcp_server.py` notifications**

Replace the notification messages (lines 229-236):

```python
                        if status == "warning":
                            days = refresh_result.get("days_until_expiry", "?")
                            Notifier.send(
                                title="Jarvis: Graph Token Expiring",
                                message=f"Token expires in ~{days} days. Run: python scripts/bootstrap_secrets.py --reauth",
                            )
                        else:
                            Notifier.send(
                                title="Jarvis: Graph Token Expired",
                                message="Run: python scripts/bootstrap_secrets.py --reauth",
                                sound="Basso",
                            )
```

**Step 3b: Update `scheduler/daemon.py` notifications**

Replace the notification messages (lines 108-117):

```python
                        if status == "warning":
                            days = result.get("days_until_expiry", "?")
                            Notifier.send(
                                title="Jarvis: Graph Token Expiring",
                                message=f"Token expires in ~{days} days. Run: python scripts/bootstrap_secrets.py --reauth",
                            )
                        else:
                            Notifier.send(
                                title="Jarvis: Graph Token Expired",
                                message="Run: python scripts/bootstrap_secrets.py --reauth",
                                sound="Basso",
                            )
```

**Step 3c: Update `graph_client.py` error message**

Replace the `GraphAuthError` message (lines 276-281):

```python
        if not self._interactive:
            raise GraphAuthError(
                "Token refresh failed and interactive auth is disabled (headless mode). "
                "Run: python scripts/bootstrap_secrets.py --reauth"
            )
```

**Step 3d: Run tests**

```bash
pytest tests/test_graph_client.py tests/test_daemon.py -x -q
```

Expected: All pass.

**Step 3e: Commit**

```bash
git add mcp_server.py scheduler/daemon.py connectors/graph_client.py
git commit -m "fix: update token expiry messages to reference --reauth command"
```

---

### Task 4: Run full test suite

```bash
pytest -x -q
```

Expected: All tests pass. No regressions.

---

## Verification Plan (Success Criteria)

Run these checks after all tasks are complete:

### V1: `--reauth` exists and shows in help
```bash
python scripts/bootstrap_secrets.py --help | grep reauth
```
Expected: `--reauth` line appears.

### V2: `bootstrap` pulls all 3 fields
```bash
python scripts/bootstrap_secrets.py --verify
```
Expected: `m365_client_id`, `m365_tenant_id`, `m365_client_secret` all present.

### V3: `--clear-tokens` covers client_secret
```bash
grep -n "client_secret" scripts/bootstrap_secrets.py
```
Expected: `client_secret` in FIELDS dict — `clear_tokens()` iterates FIELDS so it's covered.

### V4: Notification messages reference `--reauth`
```bash
grep -n "reauth" mcp_server.py scheduler/daemon.py connectors/graph_client.py
```
Expected: All three files contain `--reauth` in their notification/error messages.

### V5: 1Password fields are structured
```bash
op read "op://Employee/Jarvis - Entra Enterprise App/client_id"
op read "op://Employee/Jarvis - Entra Enterprise App/client_secret"
```
Expected: Both return values (not errors).

### V6: All tests pass
```bash
pytest -x -q
```
Expected: All pass, zero failures.

### V7: End-to-end `--reauth` works
```bash
python scripts/bootstrap_secrets.py --reauth
```
Expected: Prints device code URL + code, completes after browser sign-in, prints "Re-authentication successful."
