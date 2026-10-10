"""Conservative Windows-only adapter. No desktop imports at module import time."""
import os
from pathlib import Path
import subprocess
import time

from observation import ToolResult
from safety import Cancellation
from tools.registry import PERMITTED_KEYS


class DesktopGuardError(RuntimeError):
    """Known, safe-to-display refusal raised by a local desktop guard."""


class WindowsController:
    def __init__(self, launch_timeout: float, cancellation: Cancellation,
                 max_text_length: int = 1000) -> None:
        self.launch_timeout = launch_timeout
        self.cancellation = cancellation
        self.max_text_length = max_text_length
        self._window = None
        self._editor = None
        self._runtime_id = None
        self._pg = None

    def _load(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Computer control requires Windows")
        if self._pg is None:
            import ctypes
            import pyautogui
            from pywinauto import Desktop
            from pywinauto.uia_defines import IUIA
            self._pg = pyautogui
            self._desktop = Desktop(backend="uia")
            self._uia = IUIA()
            self._user32 = ctypes.windll.user32
            self._user32.GetForegroundWindow.restype = ctypes.c_void_p
            self._user32.GetKeyboardLayout.restype = ctypes.c_void_p
            self._user32.GetKeyboardLayout.argtypes = [ctypes.c_ulong]
            self._user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self._pg.FAILSAFE = True
        self._pg.PAUSE = 0.05

    @staticmethod
    def _read(editor) -> str:
        try:
            value = editor.iface_value.CurrentValue
        except Exception:
            value = editor.iface_text.DocumentRange.GetText(-1)
        return value.replace("\r\n", "\n").replace("\r", "\n")

    def open_notepad(self) -> ToolResult:
        self._load()
        if self._window is not None:
            return ToolResult("failed", "This task already owns a Notepad window; reopening is refused")
        if self._desktop.windows(class_name="Notepad"):
            return ToolResult("failed", "Close all existing Notepad windows first to prevent tab/session reuse")
        executable = Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe"
        subprocess.Popen([str(executable)], shell=False)
        deadline = time.monotonic() + self.launch_timeout
        while time.monotonic() < deadline:
            if self.cancellation.cancelled:
                return ToolResult("cancelled", "Cancelled during launch; Notepad may remain open")
            windows = self._desktop.windows(class_name="Notepad", visible_only=True)
            if len(windows) > 1:
                return ToolResult("failed", "Multiple Notepad windows detected; no input sent")
            if len(windows) == 1:
                window = windows[0]
                editors = [item for item in window.descendants()
                           if item.element_info.control_type in {"Edit", "Document"}
                           and item.element_info.class_name in {"Edit", "RichEditD2DPT"}
                           and item.is_visible() and item.is_enabled()
                           and item.element_info.element.CurrentIsKeyboardFocusable]
                tabs = window.descendants(control_type="TabItem")
                if len(tabs) > 1:
                    return ToolResult("failed", "Restored/multiple Notepad tabs detected; close them and retry")
                if len(editors) == 1:
                    editor = editors[0]
                    try:
                        if self._read(editor):
                            return ToolResult("failed", "Notepad restored a nonempty document; no input sent. "
                                              "Disable session restore and retry with a blank window")
                    except Exception:
                        return ToolResult("failed", "Cannot read Notepad editor through accessibility; no input sent")
                    self._window = window
                    self._editor = editor
                    self._runtime_id = tuple(editor.element_info.element.GetRuntimeId())
                    return ToolResult("verified", "One blank Notepad editor identified through Windows accessibility")
            time.sleep(0.2)
        return ToolResult("failed", "Timed out identifying a single supported Notepad editor; "
                          "Notepad may be open. No input sent")

    def _guard(self) -> None:
        if self.cancellation.cancelled:
            raise InterruptedError("Cancelled")
        self._pg.failSafeCheck()
        if not self._window or not self._editor:
            raise DesktopGuardError("Open and identify Notepad first")
        if self._user32.GetForegroundWindow() != self._window.handle:
            raise DesktopGuardError("Notepad lost foreground focus")
        focused = self._uia.iuia.GetFocusedElement()
        if tuple(focused.GetRuntimeId()) != self._runtime_id:
            raise DesktopGuardError("The identified editor no longer has keyboard focus")
        if not self._editor.is_enabled() or not self._editor.is_visible():
            raise DesktopGuardError("Notepad editor is unavailable")
        # Avoid shortcut injection from physically held modifiers. Do not release user keys.
        if any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            raise DesktopGuardError("Release Shift, Control, Alt and Windows keys first")
        if self._user32.GetKeyState(0x14) & 1:
            raise DesktopGuardError("Turn Caps Lock off first")
        thread_id = self._user32.GetWindowThreadProcessId(self._window.handle, None)
        # PyAutoGUI's write is not Unicode/layout-independent. Fail closed for other layouts.
        if self._user32.GetKeyboardLayout(thread_id) & 0xFFFFFFFF != 0x04090409:
            raise DesktopGuardError("Select the standard US English keyboard layout first")

    def _focus(self) -> None:
        self._load()
        if self._editor is None:
            raise DesktopGuardError("No owned Notepad editor")
        self._editor.set_focus()
        self._guard()

    def type_text(self, text: str) -> ToolResult:
        # Defense in depth for direct calls as well as registry calls.
        if not isinstance(text, str) or not 1 <= len(text) <= self.max_text_length:
            raise ValueError("Invalid text length")
        if any(char != "\n" and not 32 <= ord(char) <= 126 for char in text):
            raise ValueError("Unsupported character")

        try:
            self._focus()
        except DesktopGuardError as exc:
            return ToolResult("failed", f"Desktop safety check prevented typing: {exc}; no text was sent")
        except InterruptedError:
            return ToolResult("cancelled", "Typing cancelled before input; no text was sent")
        except Exception:
            return ToolResult("failed", "Could not focus and verify the agent-owned Notepad editor; "
                              "no text was sent. Check Notepad focus/accessibility before retrying")

        try:
            before = self._read(self._editor)
        except InterruptedError:
            return ToolResult("cancelled", "Typing cancelled before input; no text was sent")
        except Exception:
            return ToolResult("failed", "Could not read Notepad before typing; no text was sent. "
                              "Inspect Notepad before retrying")

        try:
            self._guard()
            # Appending avoids overwriting selected text; this fixed shortcut is not model-selectable.
            self._pg.hotkey("ctrl", "end")
        except DesktopGuardError as exc:
            return ToolResult("failed", f"Desktop safety check prevented typing: {exc}; no text was sent")
        except InterruptedError:
            return ToolResult("cancelled", "Typing cancelled before text input; no text was sent")
        except Exception:
            return ToolResult("failed", "Could not confirm focus or move the caret in Notepad; "
                              "the requested text was not typed. Inspect before retrying")

        try:
            for char in text:
                self._guard()
                if char == "\n":
                    self._pg.press("enter")
                else:
                    self._pg.write(char)
        except DesktopGuardError as exc:
            return ToolResult("failed", f"Desktop safety check stopped typing: {exc}; text may be partial. "
                              "Inspect Notepad before retrying")
        except InterruptedError:
            return ToolResult("cancelled", "Typing cancelled; text may be partial. Inspect Notepad before retrying")
        except Exception:
            return ToolResult("failed", "A keyboard input or focus check failed during typing; "
                              "text may be partial. Inspect Notepad before retrying")

        try:
            self._guard()
            after = self._read(self._editor)
        except DesktopGuardError as exc:
            return ToolResult("failed", f"Post-typing safety check failed: {exc}; inspect Notepad before retrying")
        except InterruptedError:
            return ToolResult("cancelled", "Typing may have completed but could not be verified; "
                              "inspect Notepad before retrying")
        except Exception:
            return ToolResult("failed", "Text may have been entered, but final Notepad verification failed. "
                              "Inspect Notepad before retrying")

        if after == before + text:
            return ToolResult("verified", "Exact appended text verified locally through Notepad accessibility")
        return ToolResult("failed", "Input was sent but the resulting text did not match; inspect Notepad. Do not auto-retry")

    def press_key(self, key: str) -> ToolResult:
        if not isinstance(key, str) or key not in PERMITTED_KEYS:
            raise ValueError("Key not permitted")
        self._focus()
        self._pg.press(key)
        self._guard()
        return ToolResult("unverified", "Key sent to the identified editor; resulting document/caret state not verified")
