import threading
import time

from bambucam.config import TriggerConfig, load_config
from bambucam.trigger.mock import MockTriggerProvider


def test_fire_invokes_callback():
    calls = []
    trigger = MockTriggerProvider(interval_seconds=60)
    trigger.start(callback=lambda: calls.append(1))
    try:
        trigger.fire()
        trigger.fire()
    finally:
        trigger.stop()
    assert len(calls) == 2


def test_interval_fires_repeatedly():
    fired = threading.Event()
    calls = []

    def cb():
        calls.append(1)
        if len(calls) >= 2:
            fired.set()

    trigger = MockTriggerProvider(interval_seconds=0.05)
    trigger.start(callback=cb)
    try:
        assert fired.wait(timeout=3.0), "mock trigger did not fire on interval"
    finally:
        trigger.stop()


def test_stop_halts_firing():
    calls = []
    trigger = MockTriggerProvider(interval_seconds=0.05)
    trigger.start(callback=lambda: calls.append(1))
    time.sleep(0.2)
    trigger.stop()
    count = len(calls)
    time.sleep(0.2)
    assert len(calls) == count


def test_trigger_config_defaults():
    assert TriggerConfig().interval_seconds == 5.0


def test_interval_seconds_loads_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "trigger:\n  type: mock\n  interval_seconds: 1.5\n"
    )
    config = load_config(config_file)
    assert config.trigger.type == "mock"
    assert config.trigger.interval_seconds == 1.5


def test_gpio_debounce_default_is_below_typical_pulse_width():
    """rpi-lgpio only reports an edge after the level holds for debounce_ms, so
    a debounce longer than the trigger pulse discards every pulse silently.
    The CyberBrick closes for ~100ms."""
    from bambucam.config import TriggerConfig

    assert TriggerConfig().debounce_ms < 100
