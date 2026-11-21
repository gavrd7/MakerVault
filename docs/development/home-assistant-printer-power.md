# Home Assistant — optional manual 3D printer power

Home Assistant smart plugs are a **strictly opt-in manual** MakerVault feature.
No printer monitoring, temperature control, automations, power schedules,
automatic shutdown, G-code edits, Home Assistant add-ons, or extra containers.

## Setup

1. In Home Assistant, add a local smart plug exposed as a `switch.*` entity.
   Generate a long-lived access token in your Home Assistant user profile.
2. In MakerVault **Settings → 3D Printing integrations → Home Assistant**
   enter your local base URL (e.g. `http://192.168.1.20:8123`) and token,
   enable the integration, Save, then Test connection.
   MakerVault connects **server-side**; it never sends the token to the browser.
   Docker must be able to resolve/reach the URL. LAN IP addresses are often
   simpler than mDNS `.local` names inside containers.
3. In **3D Printing → Manage Printer**, select one of the discovered
   Home Assistant switches. Each physical printer can have one switch
   assigned; the same switch cannot be assigned to multiple printers.
4. A small power icon now appears for that printer in Dashboard live
   printer cards, the 3D Printing printer card and Live Monitoring.
   An unconfigured printer, disabled integration, unassigned switch or
   user without printer-change permission gets **no control at all**.

## Controls and security

- The **on/off** button performs only Home Assistant
  `POST /api/services/switch/turn_on` or `turn_off`.
- The displayed state comes from `GET /api/states/switch.<name>`, including
  a re-read after every request. The state is **not** changed optimistically.
- Off requires confirmation; MakerVault blocks off while it detects an
  active/paused/heating/cooling job in the known printer state. When a
  printer has enabled live connections, **all** must have fresh verified idle
  telemetry; any stale, conflicting or unverified connection blocks power-off.
  Printers deliberately configured without live connections still require
  explicit confirmation; operators must verify they are cooled and inactive.
  Never use the plug as a regular means of stopping a live print.
- Only authenticated printer owners with `change_printer` permission can
  operate a plug. Administrator-level workspace permissions are required
  to configure the integration and map switches.
- The token is encrypted using a server-secret-derived Fernet key in
  MakerVault's integration record; changing `SECRET_KEY` without migrating
  token encryption means the HA token must be re-entered.
- The token and ciphertext are not returned by the public integration
  serializers, and existing generic integration PATCH routes cannot modify
  Home Assistant's endpoint.
- The server refuses arbitrary public and metadata URLs, userinfo,
  embedded paths, redirects and non-switch entities. To prevent DNS rebinding
  on unencrypted requests, HTTP requires a private IP address (such as
  `http://192.168.1.20:8123`), not a hostname; HTTPS hostnames are permitted
  with normal certificate validation. Home Assistant is intended to be on a
  trusted LAN.
- No automatic on/off, no timers, no polling loop beyond explicit component
  reads/actions.

## Validation checklist (staging)

- [ ] Integration disabled: no button on any printer or mobile layout.
- [ ] Integration enabled, printer unassigned: no button.
- [ ] Assigned printer: one button on all three views, desktop and mobile.
- [ ] Power on: switch changes and state is re-read from Home Assistant.
- [ ] Power off: confirmation required; cancel does nothing.
- [ ] Printing or cooling: power-off request refused.
- [ ] Stale, missing or disconnected live printer telemetry: power-off refused.
- [ ] API or plug unreachable: error is shown; UI does not claim success.
- [ ] Unknown Home Assistant switch state: no power command can be issued from inferred printer connectivity.
- [ ] Multiple live connections: any stale/non-idle connection blocks shutdown.
- [ ] Viewer without change permission sees no action.
- [ ] Restart MakerVault: token, enabled state and printer assignment persist.
- [ ] Other users' printers and switches cannot be controlled.
- [ ] Feature is independent of slicer availability and engine version.

No hardware has been switched during development; use a non-printer
switch or an unplugged test plug for initial staging acceptance.
