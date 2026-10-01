"""Opt-in job controls. Never dispatch arbitrary G-code or retry a command."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import timedelta

import requests
import websockets
from websockets.exceptions import WebSocketException
from django.db import transaction
from django.utils import timezone

from .models import Printer, PrinterConnection, PrinterControlRequest
from .printer_connectivity import PrinterConnectionError, normalise_creality_endpoint, normalise_printer_endpoint, poll_connection


CONTROL_ADAPTERS = {"moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron", "octoprint", "creality_local"}
ACTIONS = {"pause", "resume", "cancel"}


class PrinterControlError(RuntimeError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def job_token(snapshot):
    job = snapshot.get("job") or {}
    metadata = snapshot.get("source_metadata") or {}
    if not job.get("file_name"):
        return ""
    identity = [
        snapshot.get("state"), job.get("file_name"),
        (snapshot.get("maker_vault_job") or {}).get("job_id"),
        metadata.get("job_id"), metadata.get("print_id"), metadata.get("print_start_time"),
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def control_availability(connection):
    supported = connection.adapter in CONTROL_ADAPTERS
    snapshot = connection.last_snapshot or {}
    fresh = bool(
        connection.enabled and connection.status == "connected"
        and connection.last_seen_at
        and connection.last_seen_at >= timezone.now() - timedelta(seconds=60)
        and snapshot.get("online") is True
    )
    state = snapshot.get("state")
    ready = supported and connection.controls_enabled and fresh and bool(job_token(snapshot))
    if (snapshot.get("source_metadata") or {}).get("power_loss_recovery"):
        ready = False
    return {
        "supported": supported,
        "enabled": connection.controls_enabled,
        "job_token": job_token(snapshot) if fresh else "",
        "actions": [action for action in ("pause", "resume", "cancel") if ready and (
            (action == "pause" and state == "printing")
            or (action == "resume" and state == "paused")
            or (action == "cancel" and state in {"printing", "paused"})
        )],
    }


async def _send_creality(endpoint, action):
    params = {"stop": 1} if action == "cancel" else {"pause": int(action == "pause")}
    try:
        async with websockets.connect(
            normalise_creality_endpoint(endpoint), ping_interval=None,
            subprotocols=["wsslicer"], open_timeout=5, close_timeout=1, proxy=None,
        ) as ws:
            await asyncio.wait_for(ws.send(json.dumps({"method": "set", "params": params}, separators=(",", ":"))), timeout=5)
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise PrinterControlError("Command delivery is uncertain. Refresh the printer and check its state before trying another action.", 502) from exc


def dispatch_control(connection, action):
    if not isinstance(action, str) or action not in ACTIONS or connection.adapter not in CONTROL_ADAPTERS:
        raise PrinterControlError("That printer control is not implemented.", 400)
    if connection.adapter == "creality_local":
        asyncio.run(_send_creality(connection.endpoint_url, action))
        return
    base = normalise_printer_endpoint(connection.endpoint_url)
    headers = {"Accept": "application/json"}
    api_key = str((connection.config or {}).get("api_key") or "").strip()
    if api_key:
        headers["X-Api-Key"] = api_key
    if connection.adapter == "octoprint":
        url = base + "/api/job"
        payload = {"command": "cancel"} if action == "cancel" else {"command": "pause", "action": action}
    else:
        url = base + "/printer/print/" + action
        payload = {}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=(3, 10), allow_redirects=False)
    except requests.RequestException as exc:
        raise PrinterControlError("Command delivery is uncertain. Refresh the printer and check its state before trying another action.", 502) from exc
    if not 200 <= response.status_code < 300:
        raise PrinterControlError(f"Printer did not accept the control request (HTTP {response.status_code}). Check its state before trying another action.", 502)
    if connection.adapter != "octoprint":
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrinterControlError("Printer returned an unexpected command response. Refresh to verify its state.", 502) from exc
        if not isinstance(payload, dict) or payload.get("result") != "ok":
            raise PrinterControlError("Printer did not confirm acceptance of the command. Refresh to verify its state.", 502)


def _receipt(command):
    return {"request_id": str(command.id), "action": command.action, "status": command.status, "message": command.message}


def execute_control(connection, user, payload):
    if not isinstance(payload, dict):
        raise PrinterControlError("Request body must be a JSON object.", 400)
    action = payload.get("action")
    expected = payload.get("job_token")
    try:
        request_id = uuid.UUID(str(payload.get("request_id") or ""))
    except (TypeError, ValueError, AttributeError) as exc:
        raise PrinterControlError("A valid command request ID is required.", 400) from exc
    if not isinstance(action, str) or action not in ACTIONS or not isinstance(expected, str) or len(expected) != 64:
        raise PrinterControlError("Choose Pause, Resume or Cancel for the current job.", 400)
    if action == "cancel" and payload.get("confirmed_cancel") is not True:
        raise PrinterControlError("Confirm cancellation of the named printer and job.", 400)

    with transaction.atomic():
        # Serialize command reservations across all sources of one physical printer.
        Printer.objects.select_for_update().get(pk=connection.printer_id)
        connection = PrinterConnection.objects.get(pk=connection.pk)
        previous = PrinterControlRequest.objects.filter(pk=request_id).first()
        if previous:
            if previous.connection_id != connection.id or previous.requested_by_id != user.id or previous.action != action or previous.expected_job != expected:
                raise PrinterControlError("That command request ID is already in use.")
            return _receipt(previous)
        if action not in control_availability(connection)["actions"]:
            raise PrinterControlError("Controls are disabled, unavailable or the printer status is not current. Refresh before trying again.")
        if job_token(connection.last_snapshot) != expected:
            raise PrinterControlError("The current print has changed. Refresh and confirm the action again.")
        recent = PrinterControlRequest.objects.filter(connection__printer_id=connection.printer_id)
        if recent.filter(status="pending", created_at__gte=timezone.now() - timedelta(seconds=120)).exists() or recent.filter(status__in=["sent", "unknown"], updated_at__gte=timezone.now() - timedelta(seconds=10)).exists():
            raise PrinterControlError("A recent command is still settling. Refresh the printer before another action.")
        command = PrinterControlRequest.objects.create(id=request_id, connection=connection, requested_by=user, action=action, expected_job=expected)

    # The receipt is committed BEFORE I/O, so a crashed/uncertain send is never
    # retried by replaying the same request ID.
    try:
        snapshot = poll_connection(connection)
        connection.refresh_from_db()
        if action not in control_availability(connection)["actions"] or job_token(snapshot) != expected:
            raise PrinterControlError("The printer state or job changed. Refresh and confirm the action again.")
    except (PrinterConnectionError, PrinterControlError) as exc:
        command.status = "rejected"
        command.message = str(exc)
        command.save(update_fields=["status", "message", "updated_at"])
        raise PrinterControlError(str(exc), getattr(exc, "status", 502)) from exc
    try:
        dispatch_control(connection, action)
    except (PrinterConnectionError, PrinterControlError, RuntimeError) as exc:
        command.status = "unknown"
        command.message = "Command delivery was not confirmed. Refresh and inspect the printer before another action."
        command.save(update_fields=["status", "message", "updated_at"])
        raise PrinterControlError(command.message, 502) from exc
    command.status = "sent"
    command.message = "Command sent. Waiting for live telemetry to confirm the printer state."
    command.save(update_fields=["status", "message", "updated_at"])
    return _receipt(command)
