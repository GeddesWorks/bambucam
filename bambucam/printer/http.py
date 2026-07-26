from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from bambucam.models import PrintJob
from bambucam.printer.base import PrinterProvider

logger = logging.getLogger("bambucam")

PrintEventCallback = Callable[[str, PrintJob | None], None]


class _RequestHandler(BaseHTTPRequestHandler):
    provider: HttpPrinterProvider

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "invalid JSON"}')
            return

        event_type = data.get("event")
        if event_type not in ("print_started", "print_completed",
                              "print_cancelled", "print_failed"):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "unknown event type"}')
            return

        job = None
        if event_type == "print_started":
            job = PrintJob(
                job_id=data.get("job_id", ""),
                job_name=data.get("job_name", "unknown"),
                printer_name=data.get("printer_name", ""),
            )
            self.server._provider._current_job = job
            self.server._provider._printing = True
        elif event_type in ("print_completed", "print_cancelled", "print_failed"):
            job = self.server._provider._current_job
            self.server._provider._printing = False

        logger.info(
            "Received event: %s", event_type,
            extra={"event": event_type.upper(), "job_id": job.job_id if job else None},
        )

        if self.server._provider._event_callback:
            self.server._provider._event_callback(event_type, job)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

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
            "HTTP printer provider listening on port %d", self._port,
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
