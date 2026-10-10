"""Fake all computer-control operations; tests never import PyAutoGUI/pywinauto."""
from unittest.mock import Mock
import pytest

from observation import ToolResult
from tools.applications import open_notepad_tool
from tools.keyboard import keyboard_tools
from tools.registry import ToolRegistry


@pytest.fixture
def controller():
    value = Mock()
    value.open_notepad.return_value = ToolResult("verified", "Blank editor identified")
    value.type_text.return_value = ToolResult("verified", "Exact text verified")
    value.press_key.return_value = ToolResult("unverified", "Key sent, state unknown")
    return value


@pytest.fixture
def registry(controller):
    return ToolRegistry([open_notepad_tool(controller), *keyboard_tools(controller, 1000)])
