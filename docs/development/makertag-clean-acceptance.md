# MakerTag clean/remove — staging and physical acceptance

Companion PRs: MakerVault #165 / MakerVault-Hardware #12. Keep both **draft** until the full physical matrix is signed off.

## Before starting

1. Deploy the MakerVault feature branch to **staging only** and run migration 0073.
2. Compile and flash the firmware from the matching hardware feature branch.
3. Pair the ESP32-S3 terminal over trusted HTTPS with `tags:read`, `tags:write` and its existing NTAG215 writer capability. Ensure the account has view/change/delete MakerTag permissions for relevant tests.
4. Use **disposable, writable, unlocked NTAG215 tags** only. Do not use your production MakerTags or Creality CFS filament tags.
5. Create a test inventory item and a registered MakerTag assigned to it; write its permanent MakerVault URL to the NTAG215 using the existing confirmed process. Verify the URL resolves before testing.
6. Make a database backup before attempting physical remove/delete operations.

## Tests

### A. Clean from terminal (registration retained)
- [ ] Terminal: MakerTags → Clean MakerTag → present test tag. The correct UID and MakerTag ID appear.
- [ ] Confirm. The terminal independently reads all 496 user-data bytes after the write.
- [ ] A phone no longer reads an NDEF URL from the tag; read the tag again with the terminal (or another NFC reader) and confirm **no NDEF records remain**.
- [ ] The original MakerTag still exists in the web UI; its short URL still resolves when typed manually.
- [ ] MakerTag History reports physical NFC data cleared (not registration deletion).
- [ ] Reprogram the same registered tag using the normal MakerTag writer; verify the URL again.

### B. Clean requested from MakerVault (registration retained)
- [ ] MakerTag details → Clean NFC data → select the paired terminal → send request.
- [ ] The terminal displays the expected MakerTag; wrong UID does not progress.
- [ ] Confirm and present the exact tag. The browser reports **NFC data cleared**; the registered MakerTag and inventory item remain.
- [ ] Browser cancellation before Confirm prevents physical writes.

### C. Remove from terminal without cleaning
- [ ] Terminal: MakerTags → Remove MakerTag → **No** to cleaning.
- [ ] Present the registered tag; confirm. The same physical tag must be re-presented before server deletion.
- [ ] The MakerTag is removed from MakerVault; underlying inventory item is unchanged.
- [ ] The **physical NFC URL remains on the tag**, but opening it no longer resolves to an active MakerTag.
- [ ] Any separately recorded spool physical RFID UID remains unchanged.

### D. Remove from terminal with cleaning
- [ ] Terminal: Remove MakerTag → **Yes** to cleaning.
- [ ] Confirm. User data is erased and independently verified **before** server removal.
- [ ] MakerTag record is removed; inventory item remains; tag has no NDEF data.

### E. Remove requested from MakerVault
- [ ] Remove MakerTag without cleaning: existing server-only delete, with clear warning that physical NFC stays intact.
- [ ] Remove MakerTag with cleaning: paired terminal selection; correct tag required; physical clean/readback first; deletion only after verified completion.
- [ ] The web interface distinguishes *pending*, *NFC cleared, removal pending*, *completed*, *cancelled* and *expired*.

### F. Negative/interrupt cases — use disposable tags
- [ ] Present a **different UID** before or during the cleaning attempt: no writes or server deletion.
- [ ] Protected/locked/non-NTAG215 and unrecognised/foreign NDEF: the firmware refuses physical cleaning.
- [ ] Cancel or expire an unconfirmed request: no modification or deletion.
- [ ] Disconnect HTTPS before authorization: no physical writes.
- [ ] Drop HTTPS **after** verified cleaning but before server deletion: record remains; operation retains recoverable **NFC cleared; removal pending** state.
- [ ] Restore HTTPS and complete the same operation; a replay to a different tag is rejected.
- [ ] Permissions: remove without core.delete_makertag fails; owner isolation is enforced.
- [ ] Existing MakerTags creation/reassignment, CFS read-only material decoding, generic RFID and two-sided physical spool lookup still work.

## Merge gate

- [ ] MakerVault backend + frontend CI green, migrations checked.
- [ ] Hardware sketch, writer-regression and cleaning policy CI green.
- [ ] At least one genuine NTAG215 tested for each A–E case.
- [ ] Cancellation, wrong UID and interrupted-network safety cases physically accepted.
- [ ] Documentation and release notes updated accurately, without claiming Bambu/Elegoo tag writes.
