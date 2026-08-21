import json
import urllib.error

import pytest

from bambucam.trigger.bambuddy import BambuddyLayerTrigger


def test_url_is_built_from_base_and_printer_id():
    t = BambuddyLayerTrigger(base_url="http://bambuddy:8000/", printer_id=7)
    assert t._url == "http://bambuddy:8000/api/v1/printers/7/status"


def test_first_poll_only_establishes_baseline():
    calls = []
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: {"layer_num": 12})
    t._callback = lambda: calls.append(1)
    assert t.poll_once() is False
    assert calls == []


def test_fires_once_per_layer_increment():
    calls = []
    seq = [{"layer_num": 5}, {"layer_num": 6}, {"layer_num": 7}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: seq.pop(0))
    t._callback = lambda: calls.append(1)
    assert t.poll_once() is False  # baseline
    assert t.poll_once() is True
    assert t.poll_once() is True
    assert len(calls) == 2


def test_same_layer_does_not_fire():
    seq = [{"layer_num": 5}, {"layer_num": 5}, {"layer_num": 5}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: seq.pop(0))
    t._callback = lambda: pytest.fail("should not fire on an unchanged layer")
    t.poll_once()
    assert t.poll_once() is False
    assert t.poll_once() is False


def test_missed_polls_fire_once_not_once_per_layer():
    """Only one photo is worth taking — the scene has one current state."""
    calls = []
    seq = [{"layer_num": 5}, {"layer_num": 40}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: seq.pop(0))
    t._callback = lambda: calls.append(1)
    t.poll_once()
    assert t.poll_once() is True
    assert len(calls) == 1


def test_layer_going_backwards_rebaselines_without_firing():
    """A new print restarts at layer 1; that must not fire."""
    calls = []
    seq = [{"layer_num": 90}, {"layer_num": 1}, {"layer_num": 2}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: seq.pop(0))
    t._callback = lambda: calls.append(1)
    t.poll_once()
    assert t.poll_once() is False, "restart must not fire"
    assert t.poll_once() is True, "next layer of the new print should fire"
    assert len(calls) == 1


def test_network_error_is_survived():
    calls = []
    seq = [{"layer_num": 5}, urllib.error.URLError("down"), {"layer_num": 6}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: _raise_or(seq.pop(0)))
    t._callback = lambda: calls.append(1)
    t.poll_once()
    assert t.poll_once() is False   # error swallowed
    assert t.poll_once() is True    # recovers
    assert len(calls) == 1


def test_missing_layer_field_is_ignored():
    seq = [{"state": "IDLE"}, {}]
    t = BambuddyLayerTrigger("http://b", 1, fetch=lambda *a: seq.pop(0))
    t._callback = lambda: pytest.fail("should not fire without layer_num")
    assert t.poll_once() is False
    assert t.poll_once() is False


def test_malformed_json_is_survived():
    def fetch(*a):
        raise json.JSONDecodeError("bad", "", 0)
    t = BambuddyLayerTrigger("http://b", 1, fetch=fetch)
    assert t.poll_once() is False


def _raise_or(item):
    if isinstance(item, Exception):
        raise item
    return item
