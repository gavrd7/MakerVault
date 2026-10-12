# Hardware integration API: authentication and terminal contract

Status: **design baseline / not implemented**  
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
3. **Dedicated /api/device/v1/** (later): bearer-authenticated, narrowly scoped device routes that call the same ownership checks and domain services as the browser API.
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

## Proposed HTTP routes (not yet implemented)

Browser session + CSRF, under `/api/account/keys/`:
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
