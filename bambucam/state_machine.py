from __future__ import annotations

import json
import tempfile
from enum import Enum
from pathlib import Path
from typing import Callable


class State(Enum):
    IDLE = "IDLE"
    PRINT_STARTING = "PRINT_STARTING"
    CAPTURING = "CAPTURING"
    COMPILING = "COMPILING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    CLEANUP = "CLEANUP"
    ERROR_CAMERA = "ERROR_CAMERA"
    ERROR_COMPILE = "ERROR_COMPILE"
    ERROR_UPLOAD = "ERROR_UPLOAD"
    ERROR_STORAGE = "ERROR_STORAGE"


VALID_TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.PRINT_STARTING},
    State.PRINT_STARTING: {State.CAPTURING, State.ERROR_CAMERA},
    State.CAPTURING: {
        State.COMPILING,
        State.ERROR_CAMERA,
        State.ERROR_STORAGE,
    },
    State.COMPILING: {State.UPLOADING, State.ERROR_COMPILE, State.IDLE},
    State.UPLOADING: {State.VERIFYING, State.ERROR_UPLOAD},
    State.VERIFYING: {State.CLEANUP, State.ERROR_UPLOAD},
    State.CLEANUP: {State.IDLE},
    State.ERROR_CAMERA: {State.CAPTURING, State.COMPILING, State.IDLE},
    State.ERROR_COMPILE: {State.COMPILING, State.IDLE},
    State.ERROR_UPLOAD: {State.UPLOADING, State.IDLE},
    State.ERROR_STORAGE: {State.CAPTURING, State.IDLE},
}


class InvalidTransitionError(Exception):
    pass


class StateMachine:
    def __init__(self, on_transition: Callable[[State, State], None] | None = None):
        self._state = State.IDLE
        self._on_transition = on_transition

    @property
    def state(self) -> State:
        return self._state

    def transition_to(self, new_state: State) -> None:
        if new_state not in VALID_TRANSITIONS.get(self._state, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {new_state.value}"
            )
        old_state = self._state
        self._state = new_state
        if self._on_transition:
            self._on_transition(old_state, new_state)

    def force_state(self, state: State) -> None:
        """Set state without validation — used only for crash recovery."""
        self._state = state

    @property
    def is_error(self) -> bool:
        return self._state.name.startswith("ERROR_")

    @property
    def is_idle(self) -> bool:
        return self._state == State.IDLE

    @property
    def is_capturing(self) -> bool:
        return self._state == State.CAPTURING


def persist_state(meta_path: Path, state: State, updates: dict | None = None) -> None:
    """Atomically update state (and optional fields) in meta.json."""
    data = {}
    if meta_path.exists():
        data = json.loads(meta_path.read_text())
    data["state"] = state.value
    if updates:
        data.update(updates)
    tmp = Path(tempfile.mktemp(dir=meta_path.parent, suffix=".tmp"))
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(meta_path)


def load_state(meta_path: Path) -> State | None:
    """Read persisted state from meta.json. Returns None if file missing."""
    if not meta_path.exists():
        return None
    data = json.loads(meta_path.read_text())
    return State(data.get("state", "IDLE"))
