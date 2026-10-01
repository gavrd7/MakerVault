# PrusaLink local monitoring

**Optional · Local-first · Experimental / community validation required**

MakerVault can monitor printers that expose PrusaLink's local HTTP API. This is separate from Prusa Connect/cloud use.

## What MakerVault reads

MakerVault uses PrusaLink's documented local API endpoints for status, job and printer information. Depending on printer/firmware, the normalised live view can include:

- printer state
- current file/job
- progress
- elapsed and remaining time
- nozzle and bed temperatures
- local camera availability metadata
- printer/firmware information
- PrusaLink status warnings

The integration is read-only in v0.7.3 even though the upstream API also defines print-control operations.

## Authentication

PrusaLink installations vary by generation and firmware. MakerVault supports both:

- HTTP Digest username/password authentication used by the current PrusaLink API
- X-Api-Key authentication for compatible/legacy setups

Credentials are stored server-side and secret values are not returned to the browser.

## Add the live source

1. Add or edit the printer in **3D Printing** and enter its local hostname/IP.
2. Open **Live monitor**.
3. Choose **PrusaLink**.
4. Enter the local host/IP if it is not already filled.
5. Enter either the PrusaLink username/password or an API key, according to that printer's setup.
6. Add the source and choose **Refresh**.

Successful monitoring is shown in the same live printer cards and dashboard summaries as the other MakerVault adapters.

## Multi-material note

The first PrusaLink pass focuses on printer/job telemetry. MMU3 or future multi-material slot telemetry is only added when the printer/API actually exposes enough reliable information; MakerVault does not infer physical slots from a model name alone.

## Troubleshooting

Check that MakerVault can reach the printer's local web interface and that the credentials work in PrusaLink itself. If PrusaLink returns an authentication error, confirm whether that printer expects Digest credentials or an API key.
