from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from bambucam.models import PrintJob
from bambucam.printer.base import PrinterProvider

logger = logging.getLogger("bambucam")

PrintEventCallback = Callable[[str, PrintJob | None], None]

# Bambuddy event names → our internal event names
_BAMBUDDY_EVENT_MAP = {
    "print_start": "print_started",
    "print_complete": "print_completed",
    "print_failed": "print_failed",
    "print_stopped": "print_cancelled",
}


def _parse_bambuddy_payload(data: dict) -> tuple[str | None, PrintJob | None]:
    """Parse a Bambuddy outbound webhook payload (generic format)."""
    source = data.get("source", "")
    event_raw = data.get("event", "")

    if source != "Bambuddy" and event_raw not in _BAMBUDDY_EVENT_MAP:
        return None, None

    event = _BAMBUDDY_EVENT_MAP.get(event_raw)
    if not event:
        return None, None

    printer_name = data.get("printer", "")
    filename = data.get("filename", "unknown")
    job_name = filename.replace(".gcode", "").replace(".3mf", "")
    timestamp = data.get("timestamp", "")
    job_id = f"{job_name}-{int(time.time())}" if event == "print_started" else ""

    job = PrintJob(
        job_id=job_id,
        job_name=job_name,
        printer_name=printer_name,
    )
    return event, job


def _parse_native_payload(data: dict) -> tuple[str | None, PrintJob | None]:
    """Parse our native BambuCam event payload."""
    event = data.get("event")
    if event not in ("print_started", "print_completed",
                     "print_cancelled", "print_failed"):
        return None, None

    job = None
    if event == "print_started":
        job = PrintJob(
            job_id=data.get("job_id", ""),
            job_name=data.get("job_name", "unknown"),
            printer_name=data.get("printer_name", ""),
        )
    return event, job


class _RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        # Try Bambuddy format first, then native
        event, job = _parse_bambuddy_payload(data)
        if event is None:
            event, job = _parse_native_payload(data)

        if event is None:
            self._respond(400, {"error": "unknown event format"})
            return

        provider = self.server._provider

        if event == "print_started" and job:
            provider._current_job = job
            provider._printing = True
        elif event in ("print_completed", "print_cancelled", "print_failed"):
            if job is None:
                job = provider._current_job
            provider._printing = False

        logger.info(
            "Received event: %s (job: %s)",
            event, job.job_name if job else "unknown",
            extra={"event": event.upper().replace("PRINT_", "PRINT_"),
                   "job_id": job.job_id if job else None},
        )

        if provider._event_callback:
            provider._event_callback(event, job)

        self._respond(200, {"status": "ok"})

    def do_GET(self) -> None:
        if self.path == "/health":
            provider = self.server._provider
            self._respond(200, {
                "status": "ok",
                "printing": provider._printing,
                "current_job": provider._current_job.job_name if provider._current_job else None,
            })
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args) -> None:
        pass


class HttpPrinterProvider(PrinterProvider):
    def __init__(self, port: int = 8420):
        self._port = port
        self._current_job: PrintJob | None = None
        self._printing = False
        self._event_callback: PrintEventCallback | None = None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, callback: PrintEventCallback) -> None:
        self._event_callback = callback
        self._server = HTTPServer(("0.0.0.0", self._port), _RequestHandler)
        self._server._provider = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(
            "HTTP printer provider listening on port %d (accepts Bambuddy + native payloads)",
            self._port,
            extra={"event": "PRINTER_PROVIDER_STARTED"},
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def get_current_job(self) -> PrintJob | None:
        return self._current_job

    def get_status(self) -> str:
        return "printing" if self._printing else "idle"

    def is_printing(self) -> bool:
        return self._printing
