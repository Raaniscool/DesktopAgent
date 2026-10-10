from unittest.mock import Mock
import pytest

from observation import ToolResult
from safety import Cancellation, ConsoleApproval
from tools.registry import ValidationError


def test_type_text_schema_emphasizes_verbatim_content(registry):
    schema = next(item for item in registry.schemas() if item["name"] == "type_text")
    assert "exact complete text requested by the user" in schema["description"]


@pytest.mark.parametrize("name,args", [
    ("shell", {"command": "dir"}), ([], {}),
    ("open_notepad", {"extra": True}), ("open_notepad", []),
    ("type_text", {}), ("type_text", {"text": ""}),
    ("type_text", {"text": 123}), ("type_text", {"text": "x" * 1001}),
    ("type_text", {"text": "bad\ttext"}), ("type_text", {"text": "\x1b[2J"}),
    ("type_text", {"text": "café"}), ("type_text", {"text": "\r"}),
    ("press_key", {"key": "win"}), ("press_key", {"key": "ctrl+enter"}),
    ("press_key", {"key": ["enter"]}), ("press_key", {"key": True}),
    ("press_key", {"key": "enter", "times": 100}),
])
def test_bad_arguments_never_approve_or_execute(registry, controller, name, args):
    approve = Mock(return_value=True)
    with pytest.raises(ValidationError):
        registry.execute(name, args, approve, Cancellation())
    approve.assert_not_called()
    assert not controller.mock_calls


@pytest.mark.parametrize("answer", [False, None, "yes", 1])
def test_only_explicit_boolean_approval_executes(registry, controller, answer):
    result = registry.execute("open_notepad", {}, lambda *_: answer, Cancellation())
    assert result.status == "denied"
    controller.open_notepad.assert_not_called()


def test_approved_action_executes_once(registry, controller):
    result = registry.execute("type_text", {"text": "Hello\nWorld!"}, lambda *_: True, Cancellation())
    assert result.status == "verified"
    controller.type_text.assert_called_once_with(text="Hello\nWorld!")


def test_approver_cannot_mutate_execution(registry, controller):
    def approve(name, args):
        args["text"] = "replaced"
        return True
    registry.execute("type_text", {"text": "original"}, approve, Cancellation())
    controller.type_text.assert_called_once_with(text="original")


def test_cancellation_before_and_after_approval(registry, controller):
    token = Cancellation()
    token.cancel()
    approve = Mock(return_value=True)
    assert registry.execute("open_notepad", {}, approve, token).status == "cancelled"
    approve.assert_not_called()
    token = Cancellation()
    def cancel_on_approval(*_):
        token.cancel()
        return True
    assert registry.execute("open_notepad", {}, cancel_on_approval, token).status == "cancelled"
    controller.open_notepad.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("secret contents"), KeyboardInterrupt()])
def test_action_failure_is_reported_without_leaking_payload(registry, controller, error, caplog):
    controller.type_text.side_effect = error
    result = registry.execute("type_text", {"text": "private text"}, lambda *_: True, Cancellation())
    assert result.status == ("cancelled" if isinstance(error, KeyboardInterrupt) else "failed")
    assert "secret contents" not in result.message + caplog.text
    assert "private text" not in caplog.text


def test_invalid_result(registry, controller):
    controller.open_notepad.return_value = True
    assert registry.execute("open_notepad", {}, lambda *_: True, Cancellation()).status == "failed"


@pytest.mark.parametrize("answer,expected", [("yes", True), (" YES ", True), ("y", False), ("no", False)])
def test_console_approval(answer, expected):
    output = []
    approval = ConsoleApproval(lambda _: answer, output.append)
    assert approval("type_text", {"text": "hello\nthere"}) is expected
    assert 'hello\\nthere' in output[0]
