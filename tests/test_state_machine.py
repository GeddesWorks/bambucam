import pytest

from bambucam.state_machine import InvalidTransitionError, State, StateMachine


def test_initial_state():
    sm = StateMachine()
    assert sm.state == State.IDLE
    assert sm.is_idle


def test_valid_transition():
    sm = StateMachine()
    sm.transition_to(State.PRINT_STARTING)
    assert sm.state == State.PRINT_STARTING


def test_invalid_transition():
    sm = StateMachine()
    with pytest.raises(InvalidTransitionError):
        sm.transition_to(State.UPLOADING)


def test_full_happy_path():
    transitions = []
    sm = StateMachine(on_transition=lambda o, n: transitions.append((o, n)))

    sm.transition_to(State.PRINT_STARTING)
    sm.transition_to(State.CAPTURING)
    sm.transition_to(State.COMPILING)
    sm.transition_to(State.UPLOADING)
    sm.transition_to(State.VERIFYING)
    sm.transition_to(State.CLEANUP)
    sm.transition_to(State.IDLE)

    assert sm.is_idle
    assert len(transitions) == 7
    assert transitions[0] == (State.IDLE, State.PRINT_STARTING)
    assert transitions[-1] == (State.CLEANUP, State.IDLE)


def test_error_and_recovery():
    sm = StateMachine()
    sm.transition_to(State.PRINT_STARTING)
    sm.transition_to(State.CAPTURING)
    sm.transition_to(State.ERROR_CAMERA)
    assert sm.is_error
    sm.transition_to(State.CAPTURING)
    assert sm.is_capturing


def test_force_state():
    sm = StateMachine()
    sm.force_state(State.COMPILING)
    assert sm.state == State.COMPILING


def test_compile_error_recovery():
    sm = StateMachine()
    sm.force_state(State.COMPILING)
    sm.transition_to(State.ERROR_COMPILE)
    sm.transition_to(State.COMPILING)
    sm.transition_to(State.UPLOADING)
    assert sm.state == State.UPLOADING


def test_upload_error_recovery():
    sm = StateMachine()
    sm.force_state(State.UPLOADING)
    sm.transition_to(State.ERROR_UPLOAD)
    sm.transition_to(State.UPLOADING)
    sm.transition_to(State.VERIFYING)
    assert sm.state == State.VERIFYING
