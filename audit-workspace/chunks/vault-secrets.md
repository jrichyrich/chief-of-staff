# Vault/Secrets Layer — Chunk Audit

**Chunk**: Vault/Secrets Layer
**Files audited**:
- `vault/__init__.py`
- `vault/keychain.py`
- `scripts/bootstrap_secrets.py`
- `tests/test_keychain.py`

**Auditor**: Chunk Audit Agent
**Date**: 2026-03-12

---

## Dimension Scores

| Dimension       | Score | Notes |
|----------------|-------|-------|
| Correctness     | 4/5   | Solid core logic; one cache-coherency gap on set_secret |
| Reliability     | 4/5   | Good exception handling; missing subprocess timeout |
| Security        | 3/5   | No subprocess timeout, secret value passes through argv, no input validation |
| Testability     | 4/5   | Good mock coverage; missing several edge-case paths |
| Maintainability | 5/5   | Clean, well-documented, minimal coupling |

**Overall**: 4.0 / 5.0

---

## Findings

### F1 — No subprocess timeout (security / reliability)

**File**: `vault/keychain.py`, lines 46-56, 86-97, 126-135
**Severity**: HIGH
**Status**: Confirmed

All three `subprocess.run()` calls in `get_secret`, `set_secret`, and `delete_secret` lack a `timeout` parameter. If the `security` CLI hangs (e.g., waiting for a Keychain unlock dialog that never resolves, or a system-level lock), the calling process blocks indefinitely. Since `get_secret` is called at `config.py` import time, a hung `security` process would freeze the entire MCP server startup.

**Recommendation**: Add `timeout=10` (or similar) to all `subprocess.run()` calls. Catch `subprocess.TimeoutExpired` alongside the existing exception handlers.

Same issue exists in `scripts/bootstrap_secrets.py` lines 42-46 (`op_read`) and 121-129 (`clear_tokens`), though scripts are interactive so the risk is lower.

---

### F2 — Secret value visible in process argument list

**File**: `vault/keychain.py`, line 91 (`-w`, value)
**Severity**: MEDIUM
**Status**: Confirmed

`set_secret` passes the secret value as a command-line argument (`-w`, value). On macOS, any user can see another process's arguments via `ps aux` during the brief window the subprocess runs. The `security` CLI does not support reading the password from stdin in this mode, so there is no easy mitigation within the current approach. This is a known limitation of the macOS `security` CLI.

**Recommendation**: Document this as a known limitation. For truly sensitive values, consider using the Security framework via PyObjC directly (which avoids the CLI entirely). For the current use case (client_id, tenant_id — not actual secrets/passwords), the risk is acceptable.

---

### F3 — Cache stores None values, preventing env var updates

**File**: `vault/keychain.py`, lines 34-39
**Severity**: MEDIUM
**Status**: Confirmed

When `get_secret(key)` returns `None` (secret not found anywhere), the result is cached as `_cache[key] = None`. If a user subsequently sets the environment variable and calls `get_secret` again in the same process, the cached `None` is returned instead of the new env value. This is technically correct per the docstring ("cached after first call") but can cause confusion during debugging or dynamic configuration.

**Recommendation**: Either (a) don't cache `None` results, or (b) document clearly that `clear_secret_cache()` must be called after env changes. Option (a) is preferred since a missing secret that's later provided is a valid operational scenario.

---

### F4 — set_secret invalidates cache but does not store new value

**File**: `vault/keychain.py`, line 100
**Severity**: LOW
**Status**: Confirmed

After a successful `set_secret(key, value)`, the cache entry is popped (`_cache.pop(key, None)`) rather than updated to the new value. The next `get_secret(key)` call will re-invoke the `security` subprocess to fetch the value that was just written. This is functionally correct (avoids a stale cache if the Keychain write silently failed) but slightly wasteful.

**Recommendation**: Minor optimization opportunity. Current behavior is the safer choice — no change needed.

---

### F5 — No input validation on key parameter

**File**: `vault/keychain.py`, lines 27, 74, 115
**Severity**: LOW
**Status**: Confirmed

The `key` parameter is passed directly as a subprocess argument. While `subprocess.run()` with a list (not shell=True) prevents shell injection, there is no validation that `key` is a reasonable string. An empty string, string with newlines, or extremely long string would be passed to the `security` CLI, which would fail with a confusing error.

**Recommendation**: Add a basic guard: `if not key or not isinstance(key, str): raise ValueError(...)`. This is defense-in-depth since all current callers pass hardcoded strings.

---

### F6 — bootstrap_secrets.py op_read lacks error masking

**File**: `scripts/bootstrap_secrets.py`, line 49
**Severity**: LOW
**Status**: Confirmed

`op_read()` raises `RuntimeError` with the full `stderr` output from the `op` CLI. Depending on the 1Password CLI version, stderr could contain sensitive context (vault names, item identifiers). Since this is an interactive script run locally, the risk is minimal.

---

### F7 — Missing test: Keychain returns empty stdout

**File**: `tests/test_keychain.py`
**Severity**: LOW
**Status**: Confirmed

There is no test for the case where `security find-generic-password` returns `returncode=0` but `stdout` is empty or whitespace-only. The code handles this correctly (line 59: `if value:` after strip), but the path is untested.

---

### F8 — Missing test: subprocess.TimeoutExpired

**File**: `tests/test_keychain.py`
**Severity**: LOW (becomes MEDIUM if F1 is fixed)
**Status**: Suspected

No test covers `subprocess.TimeoutExpired`. Currently moot since there is no timeout parameter (F1), but once a timeout is added, this exception path needs coverage.

---

### F9 — Missing test: FileNotFoundError in get_secret

**File**: `tests/test_keychain.py`
**Severity**: LOW
**Status**: Confirmed

The `FileNotFoundError` catch in `_get_secret_uncached` (line 62) for when the `security` binary is not found is untested. This is a valid edge case on non-standard macOS installs or containers.

---

### F10 — Module-level cache is not thread-safe

**File**: `vault/keychain.py`, line 19
**Severity**: LOW
**Status**: Confirmed

The `_cache` dict is a plain `dict` with no locking. In a multi-threaded context, concurrent `get_secret` calls for the same key could result in duplicate subprocess calls (benign race — both would cache the same value). Since the MCP server is async (single-threaded event loop) and subprocess calls are synchronous, this is not currently exploitable. Would become relevant if the code were used from a threaded context.

---

### F11 — bootstrap_secrets FIELDS list does not include client_secret

**File**: `scripts/bootstrap_secrets.py`, line 21
**Severity**: LOW
**Status**: Confirmed

`FIELDS = ["client_id", "tenant_id"]` — the bootstrap script only handles two of the three M365 secrets. `config.py` line 165 also reads `m365_client_secret` via `get_secret()`. If a client secret is needed (for confidential app flows), it must be bootstrapped manually or added to `FIELDS`/`SECRET_KEYS`.

This may be intentional if the app uses device-code flow (public client, no client secret), but it is worth noting.

---

## Architecture Observations

1. **Clean fallback chain**: Keychain -> env var -> None. The `try/except ImportError` guard in both `config.py` and `graph_client.py` means the vault module is fully optional — the system degrades gracefully on non-macOS or when the module is unavailable.

2. **Good naming discipline**: The package is named `vault/` (not `secrets/`) to avoid shadowing Python's stdlib `secrets` module, mirroring the `apple_calendar/` pattern documented in CLAUDE.md.

3. **Single service name**: All secrets share the Keychain service name `jarvis`. This is clean but means there's no namespace separation between different secret categories. Acceptable at current scale.

4. **Import-time execution**: `config.py` calls `get_secret()` at import time (module-level constants). The caching in keychain.py mitigates repeated subprocess overhead, but any failure here affects all module imports.

---

## Summary

The vault/secrets layer is well-designed and cleanly implemented for its scope. The code is minimal, well-documented, and follows defensive patterns (exception handling, platform guards, graceful fallback). The most actionable finding is **F1 (missing subprocess timeout)** — a hung `security` process at import time could freeze the MCP server with no recovery path. **F3 (caching None)** is a usability concern worth addressing. The remaining findings are low-severity hardening opportunities.

**Priority fixes**:
1. **F1**: Add `timeout=10` to all `subprocess.run()` calls (HIGH)
2. **F3**: Don't cache `None` results, or cache with a short TTL (MEDIUM)
3. **F5**: Add basic key validation (LOW, defense-in-depth)
