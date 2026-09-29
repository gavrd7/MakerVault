# SimplyPrint

**Optional · Read-only import**

The SimplyPrint adapter imports printer state, loaded-filament context and recent print history. It does not send print jobs or change cloud printer settings.

## Before you begin

Obtain API access, an API key and your account/company ID from SimplyPrint. Access depends on that service's current account arrangements; do not assume all subscriptions include it. No SimplyPrint account is required for MakerVault's native features.

## Connect and verify

1. Open **Settings → 3D Printing** and enable SimplyPrint.
2. Enter **Account / company ID** and **API key**.
3. Choose **Recent history per sync** (the UI allows 1–100 jobs).
4. Save, use **Test connection**, then **Sync now**.
5. Review imported printer records, state, slots and recent jobs.
6. Confirm physical spool mappings before relying on imported material context.
7. Enable **Scheduled sync**, set an interval and save after the initial review.

The saved key is not returned to the browser. A blank replacement field with an “API key saved” indication does not mean the credential has been lost.

## Physical identity and history

MakerVault remains authoritative for physical inventory. Reported filament assignments do not automatically create or replace a physical spool. Explicitly link or add the actual reel using the slot/identity workflow.

Recent-history synchronisation is not a guaranteed full historical archive. Review imported jobs before entering them manually. Missing provider duration or material details may leave incomplete analytics.

## Troubleshooting

A failed test may indicate incorrect company ID, revoked key, insufficient API access or network/service failure. Check the reported error. Keep API keys out of screenshots and support messages. Replace a compromised key at SimplyPrint and then update the saved credential in MakerVault.
