# MakerTag physical NFC cleaning — implementation contract

Status: **implemented on the linked release-candidate branches; maintainer reports the complete physical release test matrix passed**. Tracks [#159](https://github.com/gavrd7/MakerVault/issues/159). Server and terminal interfaces described here are available on the feature branches, not the published releases.

## Three user-visible operations

| Operation | Physical NTAG215 NDEF user data | MakerVault MakerTag registration |
| --- | --- | --- |
| Clean MakerTag | Erased and verified empty | Retained |
| Remove MakerTag → No | Unchanged | Deleted after confirmation |
| Remove MakerTag → Yes | Erased and verified empty **first** | Deleted only after successful physical clean and server confirmation |

A MakerTag URL may cease resolving after a server-only removal while still physically stored on the tag. Independent physical spool RFID identities and inventory records are never implicitly deleted.

## Entry points

- Terminal: **MakerTags → Clean MakerTag**; **MakerTags → Remove MakerTag → Also clean NFC data? Yes / No / Back**.
- Web: MakerTag details → **Clean NFC data using terminal**; **Remove MakerTag**, with optional physical clean and explicit paired-terminal selection.
- Terminal-led operations must resolve the scanned UID and target through the authenticated owner-scoped device API. Web-led operations must bind the request to the selected MakerTag's exact ID and UID.

## Implemented device/server protocol

The `DeviceMakerTagOperation` model stores UUID request ID, owner, terminal, immutable MakerTag identity and UID, intent (clean or remove), optional clean-before-remove, source, state, expiry, physical-clean timestamp and completion timestamp. The server stores the device-reported verified-empty result as a distinct transaction/event; the physical readback still requires hardware acceptance.

- Browser create/status/cancel endpoints and device begin/pending/status/cleaned/remove endpoints follow the established paired-device patterns with authorization on every state transition.
- Server-led operations require an actively paired terminal with cleaning capability, matching owner, appropriate scopes and active user permissions.
- Distinguish physical cleaning permission from `core.delete_makertag`; **tags:write alone is not deletion authority**.
- Terminal-led removal must enforce `core.delete_makertag` against the owner or delegated interactive authorization before executing deletion.
- Recheck the exact immutable tag ID, UID, association, owner, active paired device and request authorization before the destructive physical step and before database deletion.
- The physical result must report freshly selected matching UID and independently verified **all-zero writable NDEF user pages**, rather than only saying that a URL could not be decoded.
- Complete transitions must be idempotent. Expired/cancelled requests and mismatched or reassigned tags must fail closed.
- Remove-with-clean: if physical cleaning is confirmed but database removal fails, keep a recoverable **NFC cleared; MakerTag removal pending** state tied to the same operation. Do not claim that both steps succeeded.
- Clean-only must **never** delete/unlink the MakerTag. Its success state is **NFC data cleared**, not **MakerTag deleted**.
- The current `DELETE /api/.../maker-tags/<id>/` endpoint is a hard server-side delete and deliberately does not erase physical NFC; preserve this behaviour.

## Scope and safety

Only supported, writable, unprotected NTAG215 user-data pages 4–127 may be physically modified. Preserve UID, manufacturer pages, capability container, locks, configuration, password/PACK, and separate spool UID mirrors. Reject foreign or unrecognised data by default. No CFS/Bambu/Elegoo writes. Never write to the Creality printer material database.

## Acceptance before merge

- Both terminal-led and browser-led cleaning tested with a disposable physical NTAG215 and confirmed blank by independent readback.
- Remove-without-clean confirmed to leave NFC pages unchanged; remove-with-clean proves physical wipe precedes the exact server deletion.
- Permissions, cross-owner access, wrong UID, protected/unrecognised tags, cancellation, retries, server interruption after physical wipe, expired operations and competing requests tested.
- Regression testing for MakerTag NFC assignment and existing CFS/third-party RFID readers.
- App and firmware PRs can be marked ready for review after final CI on the exact heads and documentation reconciliation; the maintainer reports the hardware matrix passed. The PR author must still verify final release artifacts after merge.


### API endpoints (feature branch)

- Browser: `POST /api/device/makertag-operation/`, `GET /api/device/makertag-operation/<id>/`, `POST /api/device/makertag-operation/<id>/cancel/`.
- Device: `POST /api/device/v1/makertag-operation/begin/`, `GET .../pending/`, `GET .../<id>/status/`, `POST .../<id>/cleaned/`, `POST .../<id>/remove/`, and `POST .../<id>/cancel/`.
- The cleaned state is durable and rediscovered from the terminal after reboot; recovering it never performs another NFC wipe without a separate operation.

**Merge status:** The maintainer has reported the full release test matrix passed on real ESP32-S3 hardware. Verify current GitHub CI against the latest docs-updated PR commits before merging, and confirm the paired app/firmware release assets when tagged.

### Consolidated terminal connection and idle work

The terminal's **four independent idle polling endpoints** have been replaced with one scoped snapshot:

- `GET /api/device/v1/pending-work/` authenticated with either `tags:read` or `tags:write` (only the corresponding authorised queues are returned), bound to the active paired terminal and account.
- JSON fields: `registration`, `ndef_write`, `lookup`, `operation`, each an existing operation payload or `null`. Write operations are omitted unless the paired key includes `tags:write`. The existing physical-clean operation can be rediscovered in durable `cleaned` state after a reboot.
- The terminal polls **once every five seconds while idle** instead of making four separate idle requests; during physical activity it suspends idle discovery. A pending snapshot is strictly **discovery, not write authorisation**. The existing operation-specific status checks, physical UID verification, cancellation and completion calls are unchanged.
- Heartbeat and periodic `/me` verification remain independent because they report device health and refresh scopes, rather than discover new work. Active cancellation/status polling remains separate to preserve safety.
- The deployed application must support the consolidated endpoint before the matching firmware is flashed. Keep both feature branches paired until their joint release.

**Reliability validation:** The previous Arduino HTTPClient firmware lost approximately 96 bytes per completed request and eventually ran out of TLS heap. The matching hardware branch now uses native ESP-IDF `esp_http_client`, a reusable verified TLS session and proper unwinding of C++ temporary buffers before deleting FreeRTOS worker tasks. In the maintainer's two-hour-plus idle recording, hundreds of requests reused one connection and idle heap remained stable, without a recovery reboot. The maintainer subsequently reported the full release test matrix passed. These are observations for the tested build, not a guarantee against future networking regressions. Keep recovery, TLS trust and the existing per-operation physical-safety checks.

