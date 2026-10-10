"""Adapter unit tests only; real Windows APIs are never loaded."""
from unittest.mock import Mock
import pytest
from safety import Cancellation
from windows_controller import WindowsController


def adapter():
    controller = WindowsController(1, Cancellation())
    controller._focus = Mock()
    controller._guard = Mock()
    controller._pg = Mock()
    controller._editor = Mock()
    return controller


def test_typing_verifies_exact_append():
    controller = adapter()
    controller._read = Mock(side_effect=["", "Hello\nworld"])
    assert controller.type_text("Hello\nworld").status == "verified"
    controller._pg.hotkey.assert_called_once_with("ctrl", "end")
    controller._pg.press.assert_called_once_with("enter")
    assert controller._pg.write.call_count == 10


def test_typing_mismatch_is_failure():
    controller = adapter()
    controller._read = Mock(side_effect=["", "wrong"])
    assert controller.type_text("hello").status == "failed"


def test_focus_loss_stops_before_input():
    controller = adapter()
    controller._read = Mock(return_value="")
    controller._guard.side_effect = RuntimeError("focus lost")
    with pytest.raises(RuntimeError):
        controller.type_text("hello")
    controller._pg.write.assert_not_called()


@pytest.mark.parametrize("text", ["", "\t", "é", "x" * 1001])
def test_direct_calls_validate(text):
    controller = adapter()
    with pytest.raises(ValueError):
        controller.type_text(text)
    controller._focus.assert_not_called()


def test_key_result_is_not_verification():
    controller = adapter()
    assert controller.press_key("enter").status == "unverified"
    with pytest.raises(ValueError):
        controller.press_key("win")
