from __future__ import annotations

import logging
import time
from typing import Callable

from bambucam.trigger.base import TriggerProvider

logger = logging.getLogger("bambucam")

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False


class GpioTriggerProvider(TriggerProvider):
    def __init__(self, pin: int = 17, edge: str = "rising",
                 debounce_ms: int = 200):
        if not _HAS_GPIO:
            raise RuntimeError("RPi.GPIO not available — not running on a Raspberry Pi?")
        self._pin = pin
        self._edge = GPIO.RISING if edge == "rising" else GPIO.FALLING
        self._debounce_ms = debounce_ms
        self._callback: Callable[[], None] | None = None
        self._last_trigger: float = 0
        self._running = False

    def start(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._running = True
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(
            self._pin,
            self._edge,
            callback=self._on_edge,
            bouncetime=self._debounce_ms,
        )
        logger.info(
            "GPIO trigger listening on pin %d (%s edge)",
            self._pin,
            "rising" if self._edge == GPIO.RISING else "falling",
            extra={"event": "TRIGGER_STARTED"},
        )

    def stop(self) -> None:
        self._running = False
        if _HAS_GPIO:
            try:
                GPIO.remove_event_detect(self._pin)
                GPIO.cleanup(self._pin)
            except Exception:
                pass

    def _on_edge(self, channel: int) -> None:
        if not self._running or self._callback is None:
            return
        now = time.monotonic()
        if (now - self._last_trigger) < (self._debounce_ms / 1000.0):
            return
        # Re-read pin to confirm signal is stable
        time.sleep(0.005)
        expected = GPIO.HIGH if self._edge == GPIO.RISING else GPIO.LOW
        if GPIO.input(self._pin) != expected:
            return
        self._last_trigger = now
        logger.debug("Trigger pulse confirmed on pin %d", self._pin,
                      extra={"event": "TRIGGER_RECEIVED"})
        self._callback()
