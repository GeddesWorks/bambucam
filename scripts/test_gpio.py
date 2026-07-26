#!/usr/bin/env python3
"""Test GPIO trigger detection."""

import signal
import sys
import time


def main() -> None:
    try:
        from bambucam.trigger.gpio import GpioTriggerProvider
    except RuntimeError:
        print("ERROR: RPi.GPIO not available. Run this on a Raspberry Pi.")
        sys.exit(1)

    pin = int(sys.argv[1]) if len(sys.argv) > 1 else 17
    edge = sys.argv[2] if len(sys.argv) > 2 else "rising"
    count = 0

    def on_trigger() -> None:
        nonlocal count
        count += 1
        print(f"[{count}] Trigger detected at {time.strftime('%H:%M:%S')}")

    trigger = GpioTriggerProvider(pin=pin, edge=edge, debounce_ms=200)
    trigger.start(on_trigger)

    print(f"Listening for {edge} edge on GPIO {pin}. Ctrl+C to stop.")

    def shutdown(signum, frame):
        trigger.stop()
        print(f"\nStopped. Total triggers: {count}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.pause()


if __name__ == "__main__":
    main()
