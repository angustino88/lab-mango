# Audit tool (Python desktop) — implementation guide

Client-side guide for the Python audit tool. The backend design it talks to is
`docs/proposals/resource-audit-scanner.md` (status: Draft, not implemented). Library names and options
below come from MSAL knowledge and were **not verified** against current Microsoft docs or run here.

## 1. Final workflow

```
start tool
  └─ sign in with Microsoft (silent if cached, else Windows broker / browser once)
       └─ sync catalog (first run: full; later: changed_since)
            └─ loop:
                 scan QR → parse uid
                 ├─ uid in local catalog? no → "Unknown tag"
                 └─ yes → show detail (fresh from server if online)
                          → auditor picks PASS / FAIL / NOT_ASSESSED + remarks
                          → save to outbox (client_audit_id, uid, result, remarks, audited_at)
       background sender: push outbox rows one by one, retry on network errors
```

## 2. Architecture

```
┌──────────────── Audit tool (Python, packaged as .exe) ─────────────┐
│ auth.py     MSAL PublicClientApplication + encrypted token cache   │
│ catalog.py  SQLite table: catalog (uid PK, resource_type, sku,     │
│             name, serial_number, location, state, condition,       │
│             updated_at) + sync cursor                              │
│ scan.py     QR input (USB scanner = keyboard input, or camera)     │
│ outbox.py   SQLite table: outbox (client_audit_id PK, uid, result, │
│             remarks, audited_at, attempts, last_error)             │
│ sender.py   background thread: POST each outbox row                │
│ ui          show detail, record result                             │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ HTTPS  Authorization: Bearer <Entra access token>
                               ▼
                  Lab Mango backend (/api/labs/...)
```

## 3. Microsoft sign-in (MSAL for Python)

Packages: `msal`, `msal[broker]` (Windows sign-in), `msal-extensions` (encrypted cache, DPAPI on Windows).

```python
import msal
from msal_extensions import build_encrypted_persistence, PersistedTokenCache

CLIENT_ID = "<frontend app client id>"            # same registration as the frontend (AAD_AUDIENCE)
AUTHORITY = "https://login.microsoftonline.com/<tenant id>"
SCOPES = ["api://<client id>/LabMango.Audit"]

cache = PersistedTokenCache(build_encrypted_persistence("labmango_audit_token_cache.bin"))

app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    enable_broker_on_windows=True,
    token_cache=cache,
)


def get_token() -> str:
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if not result:
        result = app.acquire_token_interactive(SCOPES)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "sign-in failed"))
    return result["access_token"]
```

Sign-in modes:
- Windows broker (recommended): Windows account, usually no password prompt.
- System browser: MSAL opens the browser and listens on `http://localhost`.
- Device code (fallback): `app.initiate_device_flow(SCOPES)` then `acquire_token_by_device_flow(flow)`.

Never put a client secret in the tool. Never log tokens.

## 4. Azure portal — existing frontend app registration

1. Authentication → Add a platform → "Mobile and desktop applications":
   - `http://localhost`
   - `ms-appx-web://microsoft.aad.brokerplugin/<client-id>` (for the Windows broker)
2. Expose an API → Application ID URI `api://<client-id>` → add scope `LabMango.Audit`.
3. Only if device code is used: Authentication → "Allow public client flows" = Yes.

Needs rights in the Microsoft tenant; otherwise a tenant admin does it.

## 5. QR tag

- Content: the plain `uid` only (e.g. `3f2a9c1e-7b4d-4e2a-9f6b-1c8d2e5a7b90`), no host or URL.
- Printed text next to the QR: SKU, name, serial number.
- Parse: strip whitespace, check it is a UUID.

```python
import uuid


def parse_tag(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None   # not a tag → let the auditor search by SKU in the local catalog
```

- USB barcode scanners act like a keyboard: read a line from an input field ending with Enter.

## 6. Backend calls

| Step | Call | Notes |
|---|---|---|
| Catalog sync | `GET /api/labs/audit-catalog?changed_since=<server_time>&cursor=<next_cursor>` | New endpoint. Loop until `next_cursor` is empty; save `server_time` as the next `changed_since`; delete rows with `deleted: true` |
| Equipment detail | `GET /api/labs/equipment/uid/{uid}` | Exists. Other types: show the catalog row |
| Push audit | `POST /api/labs/resources/uid/{uid}/audits` | Exists; `Idempotency-Key` is the new extension |

Push request:

```python
import requests

resp = requests.post(
    f"{BASE}/api/labs/resources/uid/{row.uid}/audits",
    headers={"Authorization": f"Bearer {get_token()}", "Idempotency-Key": str(row.client_audit_id)},
    json={"result": row.result, "remarks": row.remarks, "audited_at": row.audited_at.isoformat()},
    timeout=15,
)
```

Response handling in the sender:

| Status | Action |
|---|---|
| `201` (also with `Idempotency-Replayed: true`) | Remove the row from the outbox |
| `401` | Get a new token (silent, else interactive), retry |
| `403` | Stop; the user lacks the coordinator/admin role |
| `404` | Mark the row failed: the resource no longer exists; show it to the auditor |
| `409 request_in_progress` | Retry later |
| `422` | Mark failed and show the error (`idempotency_key_reuse` means a bug: same key, different body) |
| network error / `5xx` | Keep the row, retry with backoff (e.g. 2s, 4s, 8s … max 5 min) |

Rules:
- `client_audit_id` = `uuid4()` created **once** when the result is saved, never on each retry.
- `audited_at` = time the auditor recorded the result, not the time it was sent.

## 7. Local data protection

- Catalog and outbox are internal data: store them in the user profile, encrypted or DPAPI-protected.
- The catalog never contains license keys (the backend does not send them).
- Add a "Sign out and clear local data" action.

## 8. Packaging

- PyInstaller (`pyinstaller --onefile --windowed main.py`); include the MSAL broker runtime if used.
- Config file next to the exe (or settings screen): backend base URL, client ID, tenant ID. No secrets.

## 9. Conversation summary (decisions, 2026-11-12)

| Question | Decision |
|---|---|
| Who pushes audits? | A Python desktop tool used by a signed-in auditor, not the frontend |
| Login | Microsoft sign-in with MSAL; reuse the existing frontend app registration (add desktop platform + API scope) |
| Can the tool reuse the frontend's login? | No; it signs in itself, which feels like SSO for the user |
| API key instead? | No: no user for `auditor`, and a key in an exe can be extracted |
| Detect missing items? | Out of scope; per-resource audit results only |
| What is in the QR? | Plain `uid` only, no host; SKU, name, serial number printed as text; old SKU tags replaced now |
| Which types? | All: equipment, bench, station, room, license |
| License | Own tag stuck on its carrier hardware (option A); no-hardware licenses audited on the web |
| New backend work | Entra access-token auth, audit-catalog endpoint, `Idempotency-Key` on audit push |
| Existing drift (spec routes, digits-as-ID, SKU/name match, unused serializer) | Fixed as separate tasks |
| Owner | Repository owner (full stack) for backend, frontend, tool |
