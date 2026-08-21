from __future__ import annotations

import logging
import threading
from typing import Callable

from bambucam.trigger.base import TriggerProvider

logger = logging.getLogger("bambucam")


class MockTriggerProvider(TriggerProvider):
    """Fires trigger pulses on a fixed interval.

    Stands in for the GPIO trigger when running off the Pi (or before the
    CyberBrick is wired up) so the full pipeline can be exercised end to end.
    """

    def __init__(self, interval_seconds: float = 5.0):
        self._interval = interval_seconds
        self._callback: Callable[[], None] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "Mock trigger firing every %.1fs", self._interval,
            extra={"event": "TRIGGER_STARTED"},
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None

    def fire(self) -> None:
        """Fire a single pulse immediately."""
        if self._callback:
            self._callback()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.fire()
