# Issue #149 — Connected RFID/NFC registration protocol (draft v1)

Status: **implemented in draft PR #150 and hardware PR #6; final regression checks pending**. Baselines: MakerVault v1.3.0, handheld v0.5.1.14.

## Principles

- Web users create inventory items/spools through existing forms, not on the small terminal.
- A browser-initiated request is bound to one **owner**, one active **ConnectedDevice** (not just any API key), and one already-existing **inventory** or **spool** target.
- A session expires after 5 minutes; only one active request per selected device. Cancellation and completion are terminal states.
- Reassignment requires a registered tag owned by the user, `change_makertag` permission, and a second explicit terminal Confirm bound to a signed, short-lived challenge. The tag ID, UID, and audit events are preserved. UID-only registration does not write tag memory.
- Use existing permission checks, MakerTag validation, RFID-to-spool mirroring and audit events; never create a second registration implementation with divergent conflict rules.
- All device routes require trusted HTTPS + a paired bearer credential with `tags:write`; browser routes require login, HTTPS, normal CSRF protections and owner permissions.

## Session state

Create a persistent `DeviceTagRegistration` model (UUID primary key) with `owner`, `device`, `target_type`, `target_id`, `state` (pending, completed, cancelled), `expires_at`, optional `tag` and `completed_at`. Responses derive expired state from `expires_at` and never return other users' sessions. Store no device secrets here. Limit in-flight sessions per device under a transaction/lock, including concurrent browser requests.

## Proposed endpoints

These routes are implemented in the draft branch and are not yet in the published release.

### Browser (session + CSRF)

- `POST /api/device/tag-registration/` JSON `{device_id,target_type,target_id}`: validate ownership, active pairing, target permission, `tags:write` permission, supported target, and create a 5-minute pending request. Returns request id, selected device label, target summary, expiry.
- `GET /api/device/tag-registration/{id}/`: owner-only status: pending/completed/cancelled/expired, target summary and safe result summary.
- `POST /api/device/tag-registration/{id}/cancel/`: owner-only cancellation; deny cancellation of already completed requests.
- `GET /api/device/tag-registration/pending/?device_id={uuid}`: owner-only interrupted-session discovery to resume or cancel a previous request.

### Paired device (bearer, verified TLS)

- `GET /api/device/v1/tag-registration/pending/`: only current active request bound to `request.device_key` through a non-revoked ConnectedDevice; bounded target display. No requests belonging to other devices.
- `POST /api/device/v1/tag-registration/{id}/complete/`: JSON `{kind,uid}`; the terminal scans the UID, displays target, then submits **only after explicit physical Confirm**. Validate session, current pairing, scopes, deadline and target, then reuse safe registration transaction. Return saved tag/record summary.

The paired terminal also calls `/api/device/v1/tag-registration/{id}/status/` to detect browser cancellation and `/cancel/` to dismiss from the device. A 409 for a UID assigned to a different owner or the same target is not actionable. For a different same-owner target, the API returns a signed reassignment challenge; the terminal's second Confirm sends this binding back (90-second expiry). A retried completion of *the same successful session* returns the existing result idempotently; a cancelled/expired/revoked request cannot complete.

## UI / firmware

- From inventory/spool detail or Maker Tags shortcut: `Assign using RFID Terminal` -> select one of user's active RFID terminals -> pending dialog with countdown and cancel -> success or actionable error.
- On terminal: notification of pending registration; target summary; scan; Confirm registers / Back cancels local scan. Confirm UI must show target and UID sufficiently to prevent accidental assignment; session cancellation or timeout is honoured server-side.
- Normal scanning: `POST /api/device/v1/tags/resolve/` with `{kind,uid}`, show identified target or unregistered status. For standalone registration, reuse `records/search` and `tags/register` with appropriate permissions; leave browser handoff independent.
- Preserve GPIO, serial diagnostics, pairing state, TLS/CA trust, heartbeat, NVS and existing scan behaviour.

## Acceptance/security tests (required before merge)

1. Newly created record -> selected paired terminal -> scan and Confirm -> exactly one MakerTag, correct owner and target, updated browser.
2. Same request completion retried -> idempotent; existing tag on another target -> second device confirmation and reassignment history; same-target or different-owner tags -> no modification.
3. Wrong owner, wrong device, non-paired API key, revoked pairing, missing scope, inactive account, missing target permission -> denied.
4. Two concurrent browser requests cannot replace each other; cancelled/expired session cannot complete (including under concurrent requests).
5. CSRF required on browser mutation; HTTPS required in production for browser/session and bearer routes; no private credentials in logs/responses.
6. 4-, 7-, and 10-byte UIDs accepted as already supported; invalid kind/UID/oversized payload denied; preserve spool UID mirror consistency.
7. Existing pairing, heartbeat, Wi-Fi, TLS and read-only scan regression tests pass on the physical Rev C.3 terminal.

## Delivery order

1. Model/migration and Django endpoints with integration/security tests.
2. Browser action and session status UI.
3. Firmware lookup + session polling + on-device confirmation.
4. Staging system test; hardware acceptance; coordinated PR review; no automatic merge or release.

## Verified staging behaviour

The owner physically tested initial NTAG215 registration, MakerTag resolution, UID-preserving reassignment to a second inventory item, two-way cancellation and browser refresh/session recovery using the Rev C.3 terminal. Display centring and repeated unregistered-tag resolution were subsequently corrected and verified. The remaining release gate is a fresh backend full-suite run after the latest changes, renamed-sketch Arduino compilation, and final PR/CI review. **Do not merge solely on the basis of earlier acceptance tests.**
