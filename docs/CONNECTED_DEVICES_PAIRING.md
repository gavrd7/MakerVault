# Connected Devices pairing contract (issue #143)

This server feature extends the scoped API-key architecture merged in PR #140. It does not replace the existing `/api/device/v1/` tag, record or weighing endpoints and does not add firmware or enclosure code.

## Setup and trust

Devices must join a usable network **before** MakerVault can receive a pairing claim. A handset may display an explicitly requested WPA2 setup AP and provide a local Wi-Fi portal. Desktop users can use a local setup AP or a separate USB helper. These bootstrap interfaces are implemented in the hardware repository, **not in this PR**. The MakerVault server cannot remotely discover an unnetworked ESP32.

All pairing requests and replies require HTTPS in production, including a correctly trusted certificate and explicit CA provisioning where the server uses a private CA. Never disable certificate validation or use an RFID UID as authentication. The device must display the server-issued eight-digit code so the owner can compare it during approval.

## Pairing sequence

1. The device creates a unique stable `device_uid` and a fresh high-entropy 32-byte random proof encoded as base64url. It securely stores the proof temporarily.
2. POST `/api/device/v1/pairing/start/` with `device_uid`, `device_type` (`rfid_terminal` or `filament_scale`) and `claim_secret`. The server stores only the SHA-256 digest and returns `pairing_id`, `confirmation_code`, and a five-minute expiry. Never log the claim proof.
3. The device displays that code and pairing expiry. The user signs in to **Settings → User Account → Connected Devices → Add Device** and approves the matching code, name and minimum required scopes (default `tags:read` + `devices:status`).
4. The device POSTs `{"claim_secret":"..."}` to `/api/device/v1/pairing/<pairing_id>/complete/` until it receives `202 pending`. A successful approval delivers `api_key` only in the **first** `200 paired` response. Store it securely and delete the temporary claim proof.
5. The server stores only a hashed API key, device-owner association and metadata. Repeated completion is rejected `410`. Expired codes and claims cannot be approved or completed. A signed-in owner can revoke the bound key by unpairing.

The server cannot retransmit a missed credential. If the device crashes before saving it, unpair and repeat the workflow with a new secret and code. Re-pairing after revocation preserves the same owner and device ID and creates a fresh credential. Another account cannot take over an existing identity.

## Heartbeat

POST `/api/device/v1/heartbeat/` with a device Bearer key that has `devices:status`, optionally sending bounded `firmware_version` and `capabilities`. This updates `last_seen_at` and communicates MakerVault API reachability. The device UI must separately report Wi-Fi link, TLS/API link and local peripheral health. MakerVault lists a device as recently connected for three minutes after a heartbeat; this is not proof that the NFC reader or scale is working.

## Security and limits

- Browser list/approve/unpair endpoints require an authenticated session and retain CSRF protection. No credential is included in a browser response, URL, query string or device list.
- The unauthenticated device claim and completion endpoints use independent IP-based request limits and fail closed on cache failure. Owner approval has a separate per-account limit.
- The device must securely generate a new proof per attempt; it must not use MAC addresses, RFID tag UIDs or other predictable data as `claim_secret`.
- Scope restrictions are enforced by the existing `UserApiKey` and `require_device_scope` middleware. Tag modification still requires explicit `tags:write` and weighing commits require `spools:weight`.
- A routine Wi-Fi outage does not unpair a device or reopen setup AP. The device should retry with its stored credential after network recovery.

## Validation gate

Before merging or publishing v1.3.0: run `python manage.py makemigrations --check --dry-run`, `python manage.py migrate --noinput`, `python manage.py test core.tests.test_device_pairing core.tests.test_device_api core.tests.test_device_api_keys`, the full Django suite, frontend tests/build, and staging pairing tests over trusted HTTPS. Include expired/replayed/wrong-proof attempts, unpair, offline recovery, write-scope denial and re-pair. Real ESP32 interaction must be validated separately before exposing setup/pairing in production.


## Frozen wire contract — pairing protocol v1 (2026-10-24)

**Canonical compatibility identifier:** `makervault-device-v1` (the existing `GET /api/device/v1/me/` protocol). Pairing v1 retains the paths and all required JSON field names below. Additive response metadata is allowed; firmware MUST ignore unrecognized response fields. Breaking changes require a separate versioned API path and specification revision; never silently replace v1.

### Primary onboarding: MakerVault-led

1. In **Settings → User Account → Connected Devices → Add Device**, select `rfid_terminal` or `filament_scale`, name it, and select explicit scopes (minimum `tags:read` + `devices:status`). Store these selections only in browser state until approval.
2. The wizard offers instructions for an already-networked device, phone/local Wi-Fi setup portal, or optional desktop USB helper. These are **not server discovery or remote Wi-Fi provisioning**.
3. Start **Connections → MakerVault → Pair device** on the hardware. It generates its own fresh proof, calls `start/`, then displays the server-issued eight-digit code.
4. Type the code into MakerVault. The browser sends the chosen **device_type**, name and scopes to the session-authenticated approval API. The server MUST reject a type mismatch. The browser can then watch the device list for the approved `device_uid`; this only indicates successful registration after device-side `complete/`.
5. The device stores the one-time token first, then tests `me/` and begins heartbeats. The wizard reports paired/awaiting-device-connection separately from hardware health. Owners can later edit scopes and revoke the device.

### Alternate onboarding: terminal + phone

The terminal's local QR portal configures Wi-Fi, the MakerVault server URL and TLS trust. LAN QR setup is available when connected; temporary SoftAP only when explicitly requested while offline. Both entry points invoke **the identical** `start/` and `complete/` calls, and the owner approves in MakerVault. Manual API keys are an advanced compatibility path, not normal onboarding.

### Network and security rules

- The device uses a stable, opaque `device_uid` matching `[A-Za-z0-9._:-]{8,120}` and an **independently generated** per-attempt 32-byte CSPRNG random secret encoded as *unpadded base64url* (43 characters). The secret must remain private, including from the browser.
- Use JSON with `Content-Type: application/json`. Use **verified HTTPS** for all device requests. Public CA roots work without importing a certificate; for private/self-signed PKI explicitly provision the trusted CA/certificate and verify hostname. Do not use `setInsecure()`, HTTP fallback or credentials in URLs.
- Session-authenticated browser endpoints require CSRF headers, and device-specific endpoints accept only the headers documented below.
- Expiry is five minutes from server time; stop polling at the reported expiry. Use conservative polling (e.g. once every 2–3 seconds), don't hammer errors or rate limits.
- Never log or upload `claim_secret`, `api_key`, authorization headers, Wi-Fi passwords or private CA material. Keep the device secret and credential in protected persistent storage, and persist a successful pairing across power cycles and SSID changes.
- A credential response is **one-time and cannot be replayed**. If the response is lost before persistent storage, unpair the device and start with a fresh claim; never assume an ambiguous network timeout means the token was stored.

### Request and response examples (normative field names)

**Start — public device endpoint** (no Bearer key, no browser cookie required):

```http
POST /api/device/v1/pairing/start/
Content-Type: application/json

{"device_uid":"mv-terminal-001","device_type":"rfid_terminal","claim_secret":"<43-character base64url CSPRNG secret>"}
```

201:

```json
{"pairing_id":"11111111-2222-4333-8444-555555555555","confirmation_code":"02817463","expires_at":"2026-10-24T02:25:00+00:00"}
```

The pairing code is a **string** (leading zeros matter). The firmware displays it; the firmware does not generate it. `pairing_id` is a UUID.

**Approve — authenticated browser endpoint** (session cookie and CSRF token; never a device Bearer token):

```http
POST /api/account/connected-devices/pair/approve/
Content-Type: application/json
X-CSRFToken: <browser CSRF token>

{"confirmation_code":"02817463","device_type":"rfid_terminal","name":"Workshop reader","scopes":["tags:read","devices:status"]}
```

200:

```json
{"approved":true,"device_type":"rfid_terminal","pairing_id":"11111111-2222-4333-8444-555555555555","device_uid":"mv-terminal-001"}
```

The additional `device_type` check and response `device_uid` let the wizard verify the intended hardware and detect completion without exposing credentials.

**Complete — public device endpoint, proof-of-possession only:**

```http
POST /api/device/v1/pairing/11111111-2222-4333-8444-555555555555/complete/
Content-Type: application/json

{"claim_secret":"<same private secret as start>"}
```

While awaiting owner approval: HTTP 202 `{"status":"pending"}`.

After approval: HTTP 200:

```json
{"status":"paired","device_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","api_key":"<secret shown exactly once>"}
```

Immediately store `api_key` durably, clear the pairing secret, then verify it with `GET /api/device/v1/me/`. A second completion after success returns HTTP 410 and does not repeat the credential.

**Verify — established PR #140 scoped API, unchanged:**

```http
GET /api/device/v1/me/
Authorization: Bearer <stored-api-key>
```

200 includes `protocol:"makervault-device-v1"`, `key_name`, `scopes`, `read_only` and `capabilities`. Note that **v1 `/me/` requires `tags:read`**, so pairing defaults include it.

**Heartbeat — paired device:**

```http
POST /api/device/v1/heartbeat/
Authorization: Bearer <stored-api-key>
Content-Type: application/json

{"firmware_version":"0.4.4.2","capabilities":["rfid","nfc","wifi"],"status":{"wifi":"connected","api":"ok","hardware":"ok"}}
```

200: `{"status":"ok"}`. Requires `devices:status`; `firmware_version` up to 80 characters and `capabilities` an array of at most 25 strings of at most 60 characters each. Heartbeat updates server API last-seen; it does **not** independently establish Wi-Fi strength or hardware readiness. The optional `status` object reports device-observed `wifi`, `api`, and `hardware` state (each value `connected`, `disconnected`, `ok`, `degraded`, `error`, or `unknown`). These are device-reported observations, not server attestations; when offline or stale the UI shows them as unknown. Omitting `status` is compatible with initial pairing-v1 firmware and records no reported state.

**Owner-management endpoints** (authenticated browser session + CSRF on mutations):
- `GET /api/account/connected-devices/` → `{"rows":[...],"device_types":["rfid_terminal","filament_scale"]}`; rows include `id`, `name`, `device_uid`, `device_type`, `scopes`, `firmware_version`, `capabilities`, `reported_status`, `last_seen_at`, `revoked_at`, `online`.
- `PATCH /api/account/connected-devices/{device_id}/` → `{"name":"Workshop reader","scopes":["tags:read","devices:status","tags:write"]}`; 200 `{"item":{...}}`, effective on subsequent device requests. The underlying credential remains the same. Scope must belong to the paired device type; never silently grant write access.
- `POST /api/account/connected-devices/{device_id}/revoke/` → 200 `{"item":{...}}`. The Bearer key is revoked immediately, but the device record remains as unpaired.\n- `DELETE /api/account/connected-devices/{device_id}/` → 200 `{"deleted":true}`. After user confirmation, revoke the bound key, remove pending/old pairing claims for the UID and permanently delete the owned device record; 404 for an unknown or another owner’s device. The physical terminal must pair again using a new code.
- A revoked device can re-pair only with fresh claim credentials and owner approval. An existing active device identity cannot be claimed again, and an identity revoked by **another owner** cannot be acquired.

### Response status handling

| Status | Meaning | Firmware/browser action |
| --- | --- | --- |
| 200 | Success (paired/approved/verified/heartbeat) | Store credential before advancing device state |
| 201 | New pairing challenge issued | Display eight-digit code and expiry |
| 202 | Pairing pending owner approval | Poll conservatively until expiry |
| 400 | Malformed or unsupported payload/type/scope | Show validation error; fix inputs before retry |
| 401 | Wrong pairing proof or invalid/revoked Bearer key | Do not retry aggressively; explain authentication or revoked state |
| 403 | HTTPS required, forbidden action, owner permissions or missing scope | Show configuration/access issue; never bypass TLS |
| 404 | Pairing code or owned device not found | Recheck code/device; do not disclose other users' devices |
| 405 | Wrong method | Firmware integration mismatch |
| 409 | Existing identity, already-approved session or conflict | Show conflict; don't overwrite or silently re-register |
| 410 | Completed or expired pairing | Clear temporary secret; start a **fresh** pairing when appropriate |
| 413 | Oversized body (where provided) | Limit payload size |
| 429 | Request limit exceeded | Honour `Retry-After`; back off |
| 503 | Rate-limit cache unavailable | Fail closed; retry later |
| 5xx / network timeout | Server or network issue | Retain existing pairing; reconnect and re-verify, no automatic AP |

Error JSON is typically `{"error":"human-readable message"}`; treat the **HTTP status** as authoritative, not exact error strings. `202 pending` is not an error.

### Explicit release boundary

Firmware v0.4.4.2 currently uses manual API keys; it **cannot yet complete pairing v1**. The backend and UI are not production-ready merely because CI passes. Validate real physical ESP32 pairing, trusted TLS, token persistence, permission changes, heartbeat, offline recovery, expiry and revocation on staging before merging or publishing v1.3.0.


## End-user wizard and release documentation requirements

The MakerVault UI implements a four-step wizard: **(1) device type/name/permissions, (2) local Wi-Fi preparation, (3) mandatory trusted HTTPS setup and starting pairing on hardware, (4) entering the server-issued eight-digit code and awaiting completion**. It is intentionally user-driven: the server does not discover or provision an offline ESP32. Permission checkboxes default to `tags:read` and `devices:status`; tag writes and weight commits must be explicitly opted into.

**HTTPS must be enabled on the MakerVault server before pairing.** In production the pairing API refuses plain HTTP. The hardware must validate the server certificate and hostname; publicly signed TLS works using normal trusted roots, and private/self-signed deployments require explicit CA/certificate trust on the device. This is a prerequisite, not an optional enhancement. An HTTP site or disabled verification is not a supported hardware pairing configuration.

### Documentation publication checklist — required for v1.3.0

- Update the MakerVault README with Connected Devices capabilities, pairing prerequisites, a short onboarding route, and a link to full instructions.
- Update the separate user-guide repository with screenshots and complete end-user procedures for both MakerVault-led and terminal/phone-led onboarding: enabling HTTPS and trusting a certificate, Wi-Fi/QR/local AP bootstrap, acquiring an eight-digit code, approving read-only versus write scopes, confirming status, modifying permissions, revoking/re-pairing, and troubleshooting expired codes, TLS failures and lost credentials.
- Document the filament weighing station as a supported device *type*, distinguishing backend availability from firmware/hardware readiness.
- Use screenshots from the final tested UI and physical terminal only; older one-page-form screenshots are obsolete. Capture the wizard's four steps, device details/edit permissions and error/expiry states. Capture physical terminal code screen, LAN QR setup and connection detail screens once firmware pairing v1 is operational.
- Link to the canonical v1 API contract for firmware implementers. Keep API keys in advanced/legacy integration instructions, not in the normal pairing walkthrough.
- Do not merge PR #146 or publish v1.3.0 until documentation, automated CI, HTTPS staging pairing and real ESP32 integration are accepted.


## Connected Devices live status refresh

While the Connected Devices panel is open, the browser refreshes its device list/heartbeat information every 30 seconds without reloading the Settings page or resetting the active wizard and edit form. Polling pauses when the browser tab is hidden and resumes when it becomes visible again. The server still determines Connected versus Offline from the authenticated heartbeat (three-minute recency window), rather than inferring reachability from the browser's presence. Firmware must keep heartbeats running while its home screen is displayed.


## Physical ESP32-S3 acceptance evidence — 2026-10-24 (firmware v0.5.1.8)

Staging environment: MakerVault HTTPS on port 8443, issued under the private MakerVault Local CA. Protocol remains `makervault-device-v1`. Results below are hands-on observations reported by the hardware tester, not automated CI results.

**Passed:** eight-digit account-approved pairing, one-time device credential persistence, reboot and Wi-Fi recovery, autonomous home-screen heartbeats, permission changes including `tags:write`, rename/unpair/re-pair/delete, invalid and expired code rejection, blocked HTTPS port and restoration without re-pair, and server certificate reissue under the same trusted Local CA.

**Private CA rejection, passed:** An unrelated independent OpenSSL CA was imported as the terminal's trusted custom CA while the MakerVault server certificate remained unchanged. The firmware's manual Test HTTPS operation reported **TCP/TLS: Certificate rejected**, no HTTP API response, and native mbedTLS `-9984` (`-0x2700`, X.509 verification failure). This is positive evidence of trust-chain enforcement for that tested request, not just an HTTP connection failure.

**Recovery, passed:** Restoring the correct MakerVault Local CA without re-pairing resulted in **TCP/TLS: Verified** and **API: Authenticated** with the existing stored credential; a reboot also reauthenticated successfully.

**Remaining firmware acceptance:** (1) explicitly demonstrate certificate hostname mismatch rejection while reaching the same staging server; (2) confirm missing custom CA rejection with TLS-specific evidence (a prior blank-CA attempt only returned generic HTTP -1); (3) verify stale diagnostics clear after failed-then-successful manual HTTPS testing without reboot (planned firmware v0.5.1.9); and (4) complete the separately scoped end-to-end tag-operation firmware milestone. Hostname/missing-CA tests must not be misreported as passed until evidenced.

The stale diagnostic is a **firmware UI state bug**, not a demonstrated backend/TLS verification failure; track the correction in MakerVault-Hardware. Do not move firmware code into this PR.

**Release gate remains closed:** update illustrated user guide and both READMEs, run CI on latest PR head, confirm 30-second Connected Devices refresh on staging, complete remaining security diagnostics, and obtain final hardware acceptance before merging PR #146 or publishing v1.3.0.
