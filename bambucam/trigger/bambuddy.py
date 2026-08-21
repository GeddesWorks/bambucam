from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Callable

from bambucam.trigger.base import TriggerProvider

logger = logging.getLogger("bambucam")


def _http_get_json(url: str, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


class BambuddyLayerTrigger(TriggerProvider):
    """Fires a pulse each time Bambuddy reports a new layer.

    A software stand-in for the CyberBrick: no wiring, at the cost of polling
    latency. Bambuddy learns the layer from the printer's MQTT feed, so a pulse
    lands somewhere between the layer change and one poll interval later.
    """

    def __init__(self, base_url: str, printer_id: int, api_key: str = "",
                 poll_interval_seconds: float = 1.0, timeout_seconds: float = 5.0,
                 fetch: Callable[[str, str, float], dict] | None = None):
        self._url = f"{base_url.rstrip('/')}/api/v1/printers/{printer_id}/status"
        self._api_key = api_key
        self._interval = poll_interval_seconds
        self._timeout = timeout_seconds
        self._fetch = fetch or _http_get_json
        self._callback: Callable[[], None] | None = None
        self._last_layer: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "Bambuddy layer trigger polling %s every %.1fs",
            self._url, self._interval,
            extra={"event": "TRIGGER_STARTED"},
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._timeout + self._interval + 1)
            self._thread = None

    def poll_once(self) -> bool:
        """Poll once; return True if a pulse was fired."""
        try:
            status = self._fetch(self._url, self._api_key, self._timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
            logger.warning("Bambuddy poll failed: %s", e,
                           extra={"event": "TRIGGER_POLL_FAILED"})
            return False

        layer = status.get("layer_num")
        if not isinstance(layer, int):
            return False

        previous, self._last_layer = self._last_layer, layer

        # First reading establishes a baseline; a decrease means a new print
        # started, so re-baseline rather than firing on the way down.
        if previous is None or layer <= previous:
            return False

        # A jump of more than one layer means polls were missed. Still fire
        # once — the scene only has one current state to photograph.
        logger.debug("Layer %s -> %s", previous, layer,
                     extra={"event": "TRIGGER_RECEIVED"})
        if self._callback:
            self._callback()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._interval)
