# MakerTag physical NFC cleaning — implementation contract

Status: **design / not implemented**. Tracks [#159](https://github.com/gavrd7/MakerVault/issues/159). This document records the agreed cross-repository behaviour before adding destructive-device endpoints.

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

## Device/server protocol to implement

A shared, durable, owner-scoped operation model should store: UUID request ID, selected terminal, target MakerTag identity, expected physical UID, intent (clean or remove), optional clean-before-remove, state, expiry, completed timestamps, and a bounded audit record of the physical readback result. This is **not** an existing API yet.

- Browser create/status/cancel endpoints and device begin/pending/status/complete endpoints should follow the established paired-device patterns with authorization on every state transition.
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
- App and firmware PRs remain **draft** until CI and real hardware acceptance.
