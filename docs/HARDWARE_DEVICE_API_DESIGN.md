# Hardware integration API: authentication and terminal contract

Status: **device API implemented and staging-tested; physical ESP32 integration pending**  
Base: MakerVault v1.2.2  
First consumer: ESP32-S3 RFID/NFC terminal (RC522); second: filament weighing station.

## Existing implementation (verified)

- `backend/core/api_urls.py` exposes `/api/tags/`, `/api/tags/resolve/`, `/api/tags/<uuid>/`.
- `backend/core/api_views.py` protects these with Django `login_required` and model permissions for writes.
- `backend/core/maker_tags.py` restricts tag target resolution to owner-owned records.
- `MakerTag.normalise_code` normalises conventional hex UIDs, and `_sync_rfid_tag_to_spool` mirrors RFID Maker Tag identifiers into `Spool.rfid_uid` subject to conflict checks.
- The `MakerTag` uniqueness constraint is on `(kind, code)` globally, while resolution is owner-scoped. Preserve this behaviour initially and explicitly test cross-owner collisions; do not silently alter this constraint.
- Existing browser endpoints MUST remain session-authenticated; do not reuse their `login_required` decorators for bearer auth or relax CSRF globally.

## Intended split

1. **User Account → Security → API Keys**: user-managed keys for approved integrations; creation, list metadata, revoke, optional expiry and rotation.
2. **Settings → Connected Devices** (later): named device inventory, firmware/capabilities, owner, key association, heartbeat, pairing and revoke.
3. **Dedicated /api/device/v1/** (implemented): bearer-authenticated, narrowly scoped device routes that call the same ownership checks and domain services as the browser API.
4. **Terminal firmware** (separate repository): SPI RC522 reader, UI, Wi-Fi, verified TLS, secure token storage; never needs a MakerVault password or privileged session cookie.
5. **Weighing station** (later): reuses auth and device API; sends measurements with units and calibration provenance; only explicit confirmed operations update filament weights.

## Key lifecycle contract

- Owner can create a key when authenticated in the browser, with chosen name, explicit scopes and optional expiry.
- User sees the plaintext token **only once** at creation; never recover or return it via list/detail endpoints.
- Generate a high-entropy random secret using a CSPRNG. Use a lookup prefix/identifier plus a keyed digest or slow hash of the secret. Database stores no recoverable plaintext token. Compare secrets in constant time and avoid secret-bearing logs.
- Revoke atomically and take effect on the next request; revocation cannot be undone. Rotation issues a new key and lets owner revoke old key after provisioning the replacement.
- Expired, revoked, malformed, unknown and inactive-owner keys all fail closed. Never treat an RFID UID as an authentication credential.
- Key's effective privileges = intersection of its explicit scopes with the owner's *current* permissions and ownership. Removing the owner's permission must immediately remove API ability. Disabling the account must disable keys.
- Only accept bearer credentials on dedicated device/API paths, not normal Django browser endpoints. Keep Allauth, MFA and normal CSRF protections unchanged.
- Require HTTPS with certificate validation and do not accept credentials in URLs, query strings or logs. Rate-limit failed authentication and write requests.
- Record issued_at, expires_at, revoked_at, last_used_at (throttled updates), optional last-used device/IP summary, and audit records for creation/revocation/rotation and writes. Never record token material.
- Admin role should not automatically read an individual owner's plaintext key. Keep user-specific lists owner-scoped.
- Explicitly decide whether device API keys should have a narrower default expiration than general-purpose integration keys; allow non-expiring keys only with clear warning.

## Initial scopes

| Scope | Intent | API maturity |
| --- | --- | --- |
| `tags:read` | Resolve identity and limited target summary | Proposed |
| `tags:write` | Register/reassign Maker Tags with conflicts and audit history | Proposed |
| `inventory:read` | Fetch limited permitted inventory/target list | Proposed |
| `spools:weight` | Submit validated, confirmed weighing measurements | Reserved, no writes initially |
| `devices:status` | Device health and firmware metadata | Reserved |

No broad `admin:*` or unrestricted `write:*` scope. Restrict and version return payloads, do not expose every field from generic `/api/tags/` to a device.

## HTTP routes and planned extensions

Browser session + CSRF, under `/api/account/api-keys/`:
- `GET /` list safe metadata; `POST /` create and show secret once.
- `POST /<uuid:key_id>/revoke/` revoke key with explicit confirmation.
- Optional `POST /<uuid:key_id>/rotate/` issue replacement independently.

Device bearer API, under `/api/device/v1/`:
- `GET me/` identify authenticated owner, current scopes and server capabilities.
- `POST tags/resolve/` with explicit technology, canonical UID, optional NDEF path.
- `POST tags/register/` and `POST tags/assign/` requiring `tags:write` and corresponding owner model permissions.
- `GET records/search/` scope-limited selectable targets with pagination.
- `POST measurements/` **future**; reject until calibration and weight provenance design is agreed.

Use idempotency keys for mutation retries and avoid creating duplicate Maker Tags from Wi-Fi reconnection/retries. Distinguish unknown, retired, conflict and unauthorised results without leaking cross-owner record details. Validate all reader values as untrusted input with size bounds.

## RFID/NFC contract

- Read physical UID as bytes, transmit canonical uppercase hexadecimal and protocol/type separately.
- **MIFARE Classic / Creality CFS:** read-only UID lookup first. No default tag overwrites, authentication-key changes or undocumented sector writes. Manufacturer data decoding is a separate feature.
- **NTAG215:** UID lookup first, optional NDEF MakerVault URL writing later, after preview and confirmation. Support phone-tappable URL independent of raw UID lookup.
- Reuse MakerTag business rules for target validation, `MakerTagEvent` audit history and spool mirror handling, extracting shared service functions if necessary.
- Ensure `kind=nfc` vs `kind=rfid` is deterministic on the device, and document physical UID collisions across technologies.
- Deleting a Maker Tag must not erase physical media or inadvertently delete independently stored spool RFID identifiers.

## Weighing-station extension

A device can send a gross mass reading with units (grams), stable/tare/calibration metadata, device identity, measurement timestamp and idempotency key. Backend identifies either a filament spool or reusable reel, determines a known explicit tare (never guesses), calculates proposed net filament mass and requires a confirmed update. Keep measurement history and provenance; device cannot directly modify arbitrary `Spool.remaining_weight_g` through a generic PATCH.

## Acceptance gates before merge

- Unit tests: generation entropy, token hash storage, one-time reveal, constant-time verification, canonical scopes, expiry/revocation, account disabled, legacy session isolation and log redaction.
- API tests: owner-only key management, CSRF on browser key creation, bearer forbidden on regular browser routes, scope combinations, current permissions, unknown/retired tag resolution, duplicate scan retries, cross-user/cross-kind conflict isolation.
- Regression tests: `test_maker_tags.py` including CFS spool mirror and MakerTag deletion behaviour; existing login/MFA/roles tests.
- CI: migrations checked, Django system checks and backend tests, security scanners and frontend checks for later UI changes.
- Hardware acceptance later: RC522 MIFARE Classic and NTAG215 UID scans, repeat taps, offline/server outage, revoked key mid-session, invalid cert, unexpected power loss, and no mutation on read-only scans.

## Proposed delivery sequence

1. Schema, migration and secret/permission helpers **plus tests** (no publicly reachable bearer routes initially).
2. Owner-managed key HTTP endpoints and Security settings UI.
3. Dedicated, read-only device lookup API with minimal response and security/regression tests.
4. Device write operations and pairing/Connected Devices.
5. Terminal firmware and actual hardware validation.
6. NDEF writer and weighing station integration.

Do not merge a partial implementation that exposes key creation without secure storage, revocation and tests.


## Implemented read-only wire contract (PR #140)

All requests require the HTTP header `Authorization: Bearer <secret>` over verified HTTPS in deployment. Session cookies alone do not authenticate these routes.

- `GET /api/device/v1/me/`: requires `tags:read`; returns `protocol`, `read_only`, `key_name`, granted `scopes` and currently available `capabilities`.
- `POST /api/device/v1/tags/resolve/`: requires `tags:read` **and** current owner permission `core.view_makertag`. JSON: `{"kind":"nfc","uid":"04AABBCCDDEEFF"}` or `{"kind":"rfid","uid":"A1B2C3D4"}`. Kind is mandatory; UID is a 4-, 7- or 10-byte hex identifier. Colon/dash/space separators are accepted and canonicalised.
- Response for known tag: `{"found":true,"status":"identified","kind":"nfc","uid":"04AABBCCDDEEFF","tag":{"id":"<uuid>","label":"Box tag","target":{"type":"inventory","type_label":"Inventory item","id":"<uuid>","label":"Tagged box","subtitle":"..."}}}`.
- Response for unknown tag: `{"found":false,"status":"unregistered","kind":"nfc","uid":"04AABBCCDDEEFF"}`.
- Invalid key/expired/revoked/disabled account: HTTP 401. Insufficient scope or missing owner model permission: HTTP 403. Malformed kind/UID: HTTP 400. Missing target for otherwise known tag: HTTP 404.
- The resolve endpoint does **not** transmit raw sector data, NFC tag payload, arbitrary model fields, or credentials. Writing to physical media is not supported; server-side registration and reassignment are available through separate, explicitly confirmed actions.

Firmware should treat `found=false` as an unknown tag, never as an invitation to write automatically. Use this response format for initial ESP32 integration. No weighing-station endpoint is active yet.

The new routes must be tested on staging before release. Avoid entering bearer secrets in shell command history or posting them in issues/logs.


## Device registration and record selection (staging-tested)

- `GET /api/device/v1/records/search/?type=inventory&q=cabinet&limit=25` — requires `inventory:read` and the owner's *current* model view permission; accepts any type supported by Maker Tags, returns owner-visible `rows` with `id`, `label`, `subtitle`. Maximum 50 returned rows; search streams candidates in batches so matches beyond the first 500 records are discoverable. Catalogue-scale pagination and indexed search remain future improvements.
- `POST /api/device/v1/tags/register/` — requires `tags:write` and `core.add_makertag`. Send `{"kind":"nfc","uid":"04010203040506","target_type":"inventory","target_id":"<uuid>"}`. Checks record ownership/current view permission. First registration returns HTTP 201 and `created:true`. Repeated same registration returns HTTP 200 and `created:false`, without a second audit event. Existing identity attached elsewhere returns HTTP 409; registration must not silently reassign.
- `POST /api/device/v1/tags/assign/` — requires `tags:write` and `core.change_makertag`, same request body. Only an active tag owned by the caller can be reassigned. Successful changes return `changed:true`; repeat same assignment returns `changed:false`. Creation and reassignment reuse the browser's `_sync_rfid_tag_to_spool` and `_record_tag_event` functions.

Firmware must **confirm target choice before calling either write endpoint**. No physical NFC or CFS tag memory is written by these endpoints. The tag's UID identifies the tag, but never authenticates the user or device. Test all mutation endpoints and CFS spool UID conflict behaviour on staging before firmware integration.

## Final software review notes (PR #140)

- On device API routes, malformed or unsupported payloads return HTTP 400, and JSON bodies exceeding 1,024 bytes return HTTP 413 (including register and assign). Authentication and authorization failures return 401 or 403; registration conflicts return 409.
- Bearer tokens belong in the Authorization header only. Never copy credentials into screenshots, firmware logs or URLs.
- Tag resolution additionally checks the owner's current view permission on the linked target model.
- Read-only searches return at most 50 results, scanning owner-owned candidates in batches; cursor pagination and indexed large-catalogue search are still future enhancements.
- Registration/reassignment operate on MakerVault database records and must only occur after explicit on-device confirmation. Repeated identical operations are no-ops, with no extra history event.
- **Remaining before release:** physical RC522/TFT/encoder integration, TLS certificate and hostname validation from the ESP32, network failure/retry behavior and a deployment-level rate-limit policy for bearer login failures and write calls. Neither rate limiting nor general-purpose device pairing is implemented by this PR.

## Shared Redis device API throttles (PR #140)

Device endpoints use MakerVault's configured shared Django Redis cache. Defaults are fixed 60-second windows:

| Setting (environment variable) | Default | Key |
| --- | ---: | --- |
| `MAKERVAULT_DEVICE_AUTH_FAILS_PER_MINUTE` | 20 | `REMOTE_ADDR`, only invalid/revoked/expired/malformed bearer credentials |
| `MAKERVAULT_DEVICE_READS_PER_MINUTE` | 120 | API key identifier, for read/lookup/search requests |
| `MAKERVAULT_DEVICE_WRITES_PER_MINUTE` | 30 | API key identifier, for register/assign requests |

Values may be configured with positive integers. HTTP **429** is returned when limits are exceeded, with a `Retry-After` header giving the seconds until the current window ends. The ESP32 should wait rather than retry immediately. When shared cache access fails, device requests fail closed with **503**, instead of bypassing throttling. Browser login and ordinary session API routes are unaffected.

These are application-level controls and do not replace reverse-proxy request-size rules or a trusted proxy/client IP deployment policy. Authentication-failure limits use the direct `REMOTE_ADDR` value rather than untrusted forwarded headers: a shared proxy may cause multiple clients to share one budget. Configure the reverse proxy appropriately and validate the effective source address in the real deployment before relying on per-device IP isolation.

## General-purpose weigh station API — initial implementation (PR #140; untested)

Two bearer-authenticated `spools:weight` endpoints:
- `POST /api/device/v1/measurements/preview/`: calculate gross minus explicit tare, return proposed weight without changing any record.
- `POST /api/device/v1/measurements/confirm/`: persist a measurement (and optionally update remaining filament weight for a spool), with owner-permission checks and an idempotent `request_id` UUID. Reuse of a request ID with changed values returns 409.

Both accept:
```json
{"request_id":"<uuid>","target_type":"project","target_id":"<uuid>","gross_weight_g":"152.25","tare_weight_g":"2.25","update_inventory":false}
```
Supported initial measurement targets: `spool`, `printed_part`, `project` (a project represents an assembly/finished product until a product catalogue exists). Decimal weight strings are in grams with at most two decimal places. Only `spool` can set `update_inventory:true`, requiring the owner's current change-spool permission. Other measurements require current model view permission. Net weight must be nonnegative and neither input may exceed 1,000,000g. Confirmed measurements store the API key identity, gross/tare/net grams, timestamp, and prior spool inventory weight. They never automatically deduct part weight from print consumption.

**Important limitation:** tare is presently supplied and explicitly confirmed by the device/operator; the endpoint does not yet validate the tare against reusable-spool associations or independent scale calibration. Don't let firmware silently submit a guessed tare. In particular, physical sensor stability/calibration, per-device identity, RFID-assisted selection, weighing history UI, and catalogue-derived tare provenance remain follow-up work. These endpoints must pass staging tests and security review before use on physical devices.
