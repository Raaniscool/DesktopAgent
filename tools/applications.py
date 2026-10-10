"""Application tool declaration."""
from tools.registry import Tool


def open_notepad_tool(controller) -> Tool:
    return Tool("open_notepad", "Open and identify a new Windows Notepad window; no saving.",
                {}, (), controller.open_notepad)
