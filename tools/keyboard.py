"""Keyboard tools: no hotkeys, arbitrary key names, or OS commands."""
from tools.registry import PERMITTED_KEYS, Tool


def keyboard_tools(controller, max_text_length: int) -> list[Tool]:
    return [
        Tool("type_text", "Append printable ASCII text/newlines to agent-owned Notepad, "
             "not an arbitrary focused application. Verify through accessibility when possible.",
             {"text": {"type": "string", "minLength": 1, "maxLength": max_text_length}},
             ("text",), controller.type_text),
        Tool("press_key", "Press one permitted key in agent-owned Notepad. Navigation is not task verification.",
             {"key": {"type": "string", "enum": list(PERMITTED_KEYS)}},
             ("key",), controller.press_key),
    ]
