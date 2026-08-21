#!/usr/bin/env python3
"""Characterise an unknown trigger signal on a GPIO pin.

Unlike test_gpio.py this applies no debounce and watches both edges, so it
shows the raw shape of whatever is connected: how long a contact closure
actually lasts, whether a signal is a one-shot pulse or continuous PWM, and
whether the line is idling high or low.

Usage: probe_gpio.py [pin] [pull]
    pin   BCM pin number (default 17)
    pull  up | down | none  (default up, for a contact closure to ground)
"""

import sys
import time

SAMPLE_SECONDS = 0.0005  # 0.5ms — fine enough to resolve servo PWM (1-2ms)


def main() -> None:
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("ERROR: RPi.GPIO not available. Run this on the Pi.")
        sys.exit(1)

    pin = int(sys.argv[1]) if len(sys.argv) > 1 else 17
    pull_arg = sys.argv[2] if len(sys.argv) > 2 else "up"
    pull = {"up": GPIO.PUD_UP, "down": GPIO.PUD_DOWN, "none": GPIO.PUD_OFF}[pull_arg]

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=pull)

    level = GPIO.input(pin)
    print(f"GPIO {pin}, pull-{pull_arg}. Idle level: {'HIGH' if level else 'LOW'}")
    print("Watching both edges, no debounce. Trigger it now. Ctrl+C to stop.\n")

    changed_at = time.monotonic()
    transitions = 0
    try:
        while True:
            now_level = GPIO.input(pin)
            if now_level != level:
                now = time.monotonic()
                held_ms = (now - changed_at) * 1000
                transitions += 1
                print(
                    f"[{transitions:4d}] {time.strftime('%H:%M:%S')} "
                    f"{'HIGH' if level else 'LOW ':4} held {held_ms:9.2f} ms "
                    f"-> {'HIGH' if now_level else 'LOW'}"
                )
                level, changed_at = now_level, now
            time.sleep(SAMPLE_SECONDS)
    except KeyboardInterrupt:
        print(f"\nStopped. {transitions} transitions seen.")
        if transitions == 0:
            print("Nothing moved — the line never changed state.")
        GPIO.cleanup(pin)


if __name__ == "__main__":
    main()
