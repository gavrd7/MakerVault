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
