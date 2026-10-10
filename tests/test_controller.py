"""Adapter unit tests only; real Windows APIs are never loaded."""
from unittest.mock import Mock
import pytest
from safety import Cancellation
from windows_controller import DesktopGuardError, WindowsController


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


def test_focus_loss_stops_before_input_with_safe_stage_message():
    controller = adapter()
    controller._read = Mock(return_value="")
    controller._guard.side_effect = RuntimeError("private window text")

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "Could not confirm focus or move the caret" in result.message
    assert "private window text" not in result.message
    controller._pg.write.assert_not_called()


def test_focus_activates_top_level_hwnd_before_editor_once():
    controller = WindowsController(1, Cancellation())
    controller._load = Mock()
    controller._window = Mock(handle=123)
    controller._editor = Mock()
    controller._user32 = Mock()
    controller._user32.GetForegroundWindow.return_value = 456
    controller._user32.IsIconic.return_value = 0
    controller._user32.SetForegroundWindow.return_value = 1
    controller._wait_for_editor_focus = Mock()
    order = []
    controller._user32.SetForegroundWindow.side_effect = lambda _: order.append("window") or 1
    controller._editor.set_focus.side_effect = lambda: order.append("editor")
    controller._wait_for_editor_focus.side_effect = lambda: order.append("wait")

    controller._focus()

    assert order == ["window", "editor", "wait"]
    controller._user32.SetForegroundWindow.assert_called_once_with(123)
    controller._window.set_focus.assert_not_called()
    controller._editor.set_focus.assert_called_once_with()


def test_focus_stops_if_windows_refuses_foreground_activation():
    controller = WindowsController(1, Cancellation())
    controller._load = Mock()
    controller._window = Mock(handle=123)
    controller._editor = Mock()
    controller._user32 = Mock()
    controller._user32.GetForegroundWindow.side_effect = [456, 456]
    controller._user32.IsIconic.return_value = 0
    controller._user32.SetForegroundWindow.return_value = 0
    controller._wait_for_editor_focus = Mock()

    with pytest.raises(DesktopGuardError, match="refused to activate"):
        controller._focus()

    controller._editor.set_focus.assert_not_called()
    controller._wait_for_editor_focus.assert_not_called()
    controller._user32.SetForegroundWindow.assert_called_once_with(123)


def test_type_text_stops_without_input_if_windows_refuses_activation():
    controller = WindowsController(1, Cancellation())
    controller._load = Mock()
    controller._window = Mock(handle=123)
    controller._editor = Mock()
    controller._pg = Mock()
    controller._user32 = Mock()
    controller._user32.GetForegroundWindow.side_effect = [456, 456]
    controller._user32.IsIconic.return_value = 0
    controller._user32.SetForegroundWindow.return_value = 0

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "Windows refused to activate" in result.message
    assert "no text was sent" in result.message
    controller._pg.hotkey.assert_not_called()
    controller._pg.write.assert_not_called()


def test_editor_focus_wait_is_bounded_and_does_not_send_input(monkeypatch):
    controller = WindowsController(1, Cancellation())
    controller._window = Mock(handle=123)
    controller._runtime_id = (7, 8)
    controller._pg = Mock()
    controller._user32 = Mock()
    controller._user32.GetForegroundWindow.return_value = 0
    ticks = iter((0.0, 0.5, 1.0))
    monkeypatch.setattr("windows_controller.time.monotonic", lambda: next(ticks))
    sleep = Mock()
    monkeypatch.setattr("windows_controller.time.sleep", sleep)

    with pytest.raises(DesktopGuardError, match="did not remain foreground"):
        controller._wait_for_editor_focus(timeout=1.0)

    assert controller._user32.GetForegroundWindow.call_count == 2
    sleep.assert_called_once_with(0.05)
    assert controller._pg.failSafeCheck.call_count == 2


def test_editor_focus_wait_requires_stable_foreground_during_uia_check(monkeypatch):
    controller = WindowsController(1, Cancellation())
    controller._window = Mock(handle=123)
    controller._runtime_id = (7, 8)
    controller._pg = Mock()
    controller._user32 = Mock()
    controller._user32.GetForegroundWindow.side_effect = [123, 0, 0, 123, 123]
    focused = Mock()
    focused.GetRuntimeId.return_value = [7, 8]
    controller._uia = Mock()
    controller._uia.iuia.GetFocusedElement.return_value = focused
    ticks = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr("windows_controller.time.monotonic", lambda: next(ticks))
    sleep = Mock()
    monkeypatch.setattr("windows_controller.time.sleep", sleep)

    controller._wait_for_editor_focus(timeout=1.0)

    assert controller._user32.GetForegroundWindow.call_count == 5
    assert controller._uia.iuia.GetFocusedElement.call_count == 2
    assert sleep.call_count == 2


def test_known_desktop_guard_reason_is_reported_safely():
    controller = adapter()
    controller._guard.side_effect = DesktopGuardError("Turn Caps Lock off first")

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "Turn Caps Lock off first" in result.message
    assert "no text was sent" in result.message
    controller._pg.write.assert_not_called()


def test_pretyping_focus_failure_is_safe_and_sends_no_text():
    controller = adapter()
    controller._focus.side_effect = RuntimeError("private window text")

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "Could not focus" in result.message and "no text was sent" in result.message
    assert "private window text" not in result.message
    controller._pg.write.assert_not_called()


def test_keyboard_failure_reports_possible_partial_input_without_details():
    controller = adapter()
    controller._read = Mock(return_value="")
    controller._pg.write.side_effect = RuntimeError("sensitive platform detail")

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "text may be partial" in result.message
    assert "sensitive platform detail" not in result.message
    controller._pg.write.assert_called_once_with("h")


def test_final_verification_error_does_not_leak_platform_details():
    controller = adapter()
    controller._read = Mock(side_effect=["", RuntimeError("sensitive document detail")])

    result = controller.type_text("hello")

    assert result.status == "failed"
    assert "final Notepad verification failed" in result.message
    assert "sensitive document detail" not in result.message
    assert controller._pg.write.call_count == 5


@pytest.mark.parametrize("text", ["", "\t", "é", "x" * 1001])
def test_direct_calls_validate(text):
    controller = adapter()
    with pytest.raises(ValueError):
        controller.type_text(text)
    controller._focus.assert_not_called()


def test_key_result_is_not_verification():
    controller = adapter()
    assert controller.press_key("enter").status == "unverified"
    assert controller._guard.call_count == 2
    with pytest.raises(ValueError):
        controller.press_key("win")
