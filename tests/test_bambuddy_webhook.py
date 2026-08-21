import http.client
import json

import pytest

from bambucam.printer.http import (
    HttpPrinterProvider,
    _parse_bambuddy_payload,
    _parse_native_payload,
)


def test_bambuddy_print_start():
    payload = {
        "title": "Print Started",
        "message": "benchy.gcode started on Jeff",
        "timestamp": "2026-08-21T14:30:00.000",
        "source": "Bambuddy",
        "event": "print_start",
        "printer": "Jeff",
        "filename": "benchy.gcode",
        "duration": "0h 0m",
        "progress": "0",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert event == "print_started"
    assert job is not None
    assert job.job_name == "benchy"
    assert job.printer_name == "Jeff"


def test_bambuddy_print_complete():
    payload = {
        "source": "Bambuddy",
        "event": "print_complete",
        "printer": "Jeff",
        "filename": "benchy.gcode",
        "duration": "1h 23m",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert event == "print_completed"


def test_bambuddy_print_failed():
    payload = {
        "source": "Bambuddy",
        "event": "print_failed",
        "printer": "Jeff",
        "filename": "test.3mf",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert event == "print_failed"
    assert job.job_name == "test"


def test_bambuddy_print_stopped():
    payload = {
        "source": "Bambuddy",
        "event": "print_stopped",
        "printer": "Jeff",
        "filename": "cube.gcode",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert event == "print_cancelled"


def test_bambuddy_unknown_event():
    payload = {
        "source": "Bambuddy",
        "event": "filament_low",
        "printer": "Jeff",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert event is None


def test_native_payload_start():
    payload = {
        "event": "print_started",
        "job_id": "abc123",
        "job_name": "benchy",
        "printer_name": "Jeff",
    }
    event, job = _parse_native_payload(payload)
    assert event == "print_started"
    assert job.job_id == "abc123"


def test_native_payload_completed():
    payload = {"event": "print_completed"}
    event, job = _parse_native_payload(payload)
    assert event == "print_completed"
    assert job is None


def test_non_bambuddy_non_native_rejected():
    payload = {"something": "else"}
    event, job = _parse_bambuddy_payload(payload)
    assert event is None
    event, job = _parse_native_payload(payload)
    assert event is None


def test_3mf_extension_stripped():
    payload = {
        "source": "Bambuddy",
        "event": "print_start",
        "printer": "Jeff",
        "filename": "cool-model.3mf",
    }
    event, job = _parse_bambuddy_payload(payload)
    assert job.job_name == "cool-model"


def _post(port, payload):
    body = json.dumps(payload).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/", body, {"Content-Type": "application/json"})
    response = conn.getresponse()
    status, data = response.status, json.loads(response.read())
    conn.close()
    return status, data


@pytest.fixture
def provider():
    p = HttpPrinterProvider(port=0)
    p.start(callback=lambda event, job: None)
    try:
        yield p, p._server.server_address[1]
    finally:
        p.stop()


def test_test_notification_is_acknowledged(provider):
    """Bambuddy's 'Test' button sends an event-less payload. Answering 200
    keeps the provider from being marked failed in Bambuddy's UI."""
    p, port = provider
    status, data = _post(port, {
        "title": "Bambuddy Test",
        "message": "This is a test notification.",
        "timestamp": "2026-08-20T19:49:22",
        "source": "Bambuddy",
    })
    assert status == 200
    assert data == {"status": "ignored"}
    assert p.is_printing() is False


def test_non_print_bambuddy_event_is_acknowledged(provider):
    _, port = provider
    status, data = _post(port, {"source": "Bambuddy", "event": "printer_offline",
                                "printer": "Jeff"})
    assert status == 200
    assert data == {"status": "ignored"}


def test_unrecognised_payload_still_rejected(provider):
    _, port = provider
    status, _data = _post(port, {"hello": "world"})
    assert status == 400
