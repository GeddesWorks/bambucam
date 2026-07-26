import json

from bambucam.state_machine import State, load_state, persist_state


def test_persist_and_load(tmp_path):
    meta_path = tmp_path / "meta.json"
    persist_state(meta_path, State.CAPTURING, {"frame_count": 10})

    state = load_state(meta_path)
    assert state == State.CAPTURING

    data = json.loads(meta_path.read_text())
    assert data["frame_count"] == 10


def test_load_missing_file(tmp_path):
    assert load_state(tmp_path / "nonexistent.json") is None


def test_atomic_write(tmp_path):
    meta_path = tmp_path / "meta.json"
    persist_state(meta_path, State.IDLE, {"job_id": "test1"})
    persist_state(meta_path, State.CAPTURING, {"job_id": "test1", "frame_count": 5})

    data = json.loads(meta_path.read_text())
    assert data["state"] == "CAPTURING"
    assert data["frame_count"] == 5
