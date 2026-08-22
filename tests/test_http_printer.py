import pytest

def test_health_clears_current_job_when_the_print_finishes(free_port):
    """An idle daemon reporting a finished print as current_job makes /health
    useless for telling whether a print is actually loaded."""
    import json
    import urllib.request

    from bambucam.printer.http import HttpPrinterProvider

    provider = HttpPrinterProvider(port=free_port)
    provider.start(callback=lambda job, event: None)
    try:
        base = f"http://127.0.0.1:{free_port}/"

        def post(payload):
            req = urllib.request.Request(
                base, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()

        def health():
            with urllib.request.urlopen(base + "health", timeout=5) as r:
                return json.loads(r.read())

        post({"event": "print_start", "filename": "thing.gcode", "printer": "Jeff"})
        assert health()["printing"] is True
        assert health()["current_job"] == "thing"

        post({"event": "print_complete", "filename": "thing.gcode", "printer": "Jeff"})
        h = health()
        assert h["printing"] is False
        assert h["current_job"] is None, "finished print must not linger in /health"
    finally:
        provider.stop()


@pytest.fixture
def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
