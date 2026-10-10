"""Conservative Windows-only adapter. No desktop imports at module import time."""
import logging
import os
from pathlib import Path
import subprocess
import time

from observation import ToolResult
from safety import Cancellation
from tools.registry import PERMITTED_KEYS
from windows_process_diagnostics import (
    capture_process_handle_identity,
    capture_process_hierarchy,
    summarize_process_relationship,
    verify_direct_launch_child,
)


logger = logging.getLogger(__name__)


class DesktopGuardError(RuntimeError):
    """Known, safe-to-display refusal raised by a local desktop guard."""


class WindowsController:
    def __init__(self, launch_timeout: float, cancellation: Cancellation,
                 max_text_length: int = 1000, process_diagnostics: bool = False) -> None:
        self.launch_timeout = launch_timeout
        self.cancellation = cancellation
        self.max_text_length = max_text_length
        self.process_diagnostics = process_diagnostics
        self._window = None
        self._editor = None
        self._runtime_id = None
        self._launched_process_id = None
        self._launch_executable_path = None
        self._launch_process_diagnostics = None
        self._launch_process_handle_identity = None
        self._last_process_relationship_diagnostics = None
        self._window_ownership_basis = None
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
            self._user32.IsIconic.argtypes = [ctypes.c_void_p]
            self._user32.IsIconic.restype = ctypes.c_int
            self._user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._user32.ShowWindow.restype = ctypes.c_int
            self._user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            self._user32.SetForegroundWindow.restype = ctypes.c_int
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
            provider = "UIA.ValuePattern"
        except Exception as exc:
            logger.debug("desktop_stage=text_readback provider=UIA.ValuePattern status=unavailable exception_type=%s",
                         type(exc).__name__)
            try:
                value = editor.iface_text.DocumentRange.GetText(-1)
                provider = "UIA.TextPattern"
            except Exception as text_exc:
                logger.debug("desktop_stage=text_readback provider=UIA.TextPattern status=failed exception_type=%s",
                             type(text_exc).__name__)
                raise
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        logger.debug("desktop_stage=text_readback provider=%s status=read character_count=%d",
                     provider, len(normalized))
        return normalized

    def open_notepad(self) -> ToolResult:
        self._load()
        if self._window is not None:
            logger.debug("desktop_stage=window_discovery status=failed reason=window_already_owned")
            return ToolResult("failed", "This task already owns a Notepad window; reopening is refused")
        self._launched_process_id = None
        self._launch_executable_path = None
        self._launch_process_diagnostics = None
        self._launch_process_handle_identity = None
        self._last_process_relationship_diagnostics = None
        self._window_ownership_basis = None
        existing = self._desktop.windows(class_name="Notepad")
        logger.debug("desktop_stage=window_discovery status=checked existing_notepad_count=%d", len(existing))
        if existing:
            logger.debug("desktop_stage=window_discovery status=failed reason=preexisting_window")
            return ToolResult("failed", "Close all existing Notepad windows first to prevent tab/session reuse")
        executable = Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe"
        self._launch_executable_path = str(executable)
        process = subprocess.Popen([self._launch_executable_path], shell=False)
        self._launched_process_id = process.pid
        logger.debug("desktop_stage=window_discovery status=launch_requested executable=notepad.exe "
                     "launched_process_id=%s", self._launched_process_id)
        try:
            process_handle = getattr(process, "_handle", None)
            self._launch_process_handle_identity = capture_process_handle_identity(
                process_handle, self._launched_process_id)
        except Exception as exc:
            self._launch_process_handle_identity = {
                "status": "error",
                "exception_type": type(exc).__name__,
                "pid": self._launched_process_id,
            }
        if self.process_diagnostics:
            try:
                self._launch_process_diagnostics = capture_process_hierarchy((self._launched_process_id,))
            except Exception as exc:
                self._launch_process_diagnostics = {
                    "status": "error",
                    "exception_type": type(exc).__name__,
                    "requested_pids": [self._launched_process_id],
                    "processes": {},
                    "chains": {},
                }
        deadline = time.monotonic() + self.launch_timeout
        last_visible_count = None
        last_editor_count = None
        last_tab_count = None
        while time.monotonic() < deadline:
            if self.cancellation.cancelled:
                logger.debug("desktop_stage=window_discovery status=cancelled")
                return ToolResult("cancelled", "Cancelled during launch; Notepad may remain open")
            windows = self._desktop.windows(class_name="Notepad", visible_only=True)
            if len(windows) != last_visible_count:
                logger.debug("desktop_stage=window_discovery visible_window_count=%d", len(windows))
                last_visible_count = len(windows)
            if len(windows) > 1:
                logger.debug("desktop_stage=window_discovery status=failed reason=multiple_windows count=%d",
                             len(windows))
                return ToolResult("failed", "Multiple Notepad windows detected; no input sent")
            if len(windows) == 1:
                window = windows[0]
                window_process_id = window.element_info.process_id
                if window_process_id != self._launched_process_id:
                    try:
                        window_hwnd = hex(int(window.handle))
                    except (TypeError, ValueError, OverflowError):
                        window_hwnd = None
                    try:
                        window_class = window.element_info.class_name
                    except Exception as exc:
                        window_class = f"unavailable:{type(exc).__name__}"
                    self._last_process_relationship_diagnostics = self._diagnose_process_mismatch(
                        process, window_process_id, window_hwnd, window_class)
                    if not self._last_process_relationship_diagnostics["ownership_confirmed"]:
                        logger.info("desktop_stage=window_discovery status=failed reason=process_mismatch "
                                    "hwnd=%s window_class=%s launched_process_id=%s window_process_id=%s "
                                    "ownership_confirmed=false input_sent=false",
                                    window_hwnd, window_class, self._launched_process_id, window_process_id)
                        return ToolResult("failed", "Could not confirm that the Notepad window belongs to the "
                                          "launched process; no input sent")
                    self._window_ownership_basis = "verified_direct_child"
                    logger.info("desktop_stage=window_discovery status=verified "
                                "reason=verified_direct_launch_child hwnd=%s window_class=%s "
                                "launched_process_id=%s window_process_id=%s ownership_confirmed=true",
                                window_hwnd, window_class, self._launched_process_id, window_process_id)
                else:
                    self._window_ownership_basis = "launch_pid_match"
                editors = [item for item in window.descendants()
                           if item.element_info.control_type in {"Edit", "Document"}
                           and item.element_info.class_name in {"Edit", "RichEditD2DPT"}
                           and item.is_visible() and item.is_enabled()
                           and item.element_info.element.CurrentIsKeyboardFocusable]
                tabs = window.descendants(control_type="TabItem")
                if len(editors) != last_editor_count or len(tabs) != last_tab_count:
                    logger.debug("desktop_stage=editor_identification editor_candidate_count=%d tab_count=%d",
                                 len(editors), len(tabs))
                    last_editor_count, last_tab_count = len(editors), len(tabs)
                if len(tabs) > 1:
                    logger.debug("desktop_stage=editor_identification status=failed reason=multiple_tabs")
                    return ToolResult("failed", "Restored/multiple Notepad tabs detected; close them and retry")
                if len(editors) == 1:
                    editor = editors[0]
                    try:
                        existing_text = self._read(editor)
                        if existing_text:
                            logger.debug("desktop_stage=editor_identification status=failed reason=not_blank "
                                         "character_count=%d", len(existing_text))
                            return ToolResult("failed", "Notepad restored a nonempty document; no input sent. "
                                              "Disable session restore and retry with a blank window")
                    except Exception as exc:
                        logger.debug("desktop_stage=editor_identification status=failed reason=read_error "
                                     "exception_type=%s", type(exc).__name__)
                        return ToolResult("failed", "Cannot read Notepad editor through accessibility; no input sent")
                    self._window = window
                    self._editor = editor
                    self._runtime_id = tuple(editor.element_info.element.GetRuntimeId())
                    logger.info("desktop_stage=window_discovery status=identified hwnd=%r class=%s process_id=%s",
                                window.handle, window.element_info.class_name, window.element_info.process_id)
                    logger.info("desktop_stage=editor_identification status=identified class=%s control_type=%s "
                                "visible=%s enabled=%s focusable=true blank=true",
                                editor.element_info.class_name, editor.element_info.control_type,
                                editor.is_visible(), editor.is_enabled())
                    return ToolResult("verified", "One blank Notepad editor identified through Windows accessibility")
        logger.debug("desktop_stage=window_discovery status=timeout visible_window_count=%r "
                     "editor_candidate_count=%r tab_count=%r",
                     last_visible_count, last_editor_count, last_tab_count)
        return ToolResult("failed", "Timed out identifying a single supported Notepad editor; "
                          "Notepad may be open. No input sent")

    def _diagnose_process_mismatch(self, launch_process, window_process_id, window_hwnd, window_class):
        """Capture read-only evidence and verify only a directly spawned Notepad child."""
        launched_pid = self._launched_process_id
        try:
            current_snapshot = capture_process_hierarchy((launched_pid, window_process_id))
        except Exception as exc:
            current_snapshot = {
                "status": "error",
                "exception_type": type(exc).__name__,
                "requested_pids": [launched_pid, window_process_id],
                "processes": {},
                "chains": {},
            }
        try:
            process_handle = getattr(launch_process, "_handle", None)
            launch_handle_identity = capture_process_handle_identity(process_handle, launched_pid)
        except Exception as exc:
            launch_handle_identity = {
                "status": "error",
                "exception_type": type(exc).__name__,
                "pid": launched_pid,
            }
        try:
            relationship = summarize_process_relationship(
                launched_pid, window_process_id,
                self._launch_process_diagnostics or {}, current_snapshot)
            ownership = verify_direct_launch_child(
                launched_pid, window_process_id, launch_handle_identity, current_snapshot,
                self._launch_process_handle_identity)
        except Exception as exc:
            relationship = {
                "classification": "diagnostics_failed",
                "launch_pid": launched_pid,
                "window_pid": window_process_id,
                "ownership_confirmed": False,
            }
            ownership = {
                "classification": "direct_launch_child_evidence_incomplete",
                "exception_type": type(exc).__name__,
                "ownership_confirmed": False,
            }

        return {
            "read_only": True,
            "launch_requested_executable_path": self._launch_executable_path,
            "launched_pid": launched_pid,
            "window_pid": window_process_id,
            "window_hwnd": window_hwnd,
            "window_class": window_class,
            "launch_process_at_start": self._launch_process_diagnostics,
            "launch_process_handle_at_start": self._launch_process_handle_identity,
            "launch_process_handle_at_mismatch": launch_handle_identity,
            "current_process_snapshot": current_snapshot,
            "relationship": relationship,
            "ownership_verification": ownership,
            "ownership_confirmed": ownership.get("ownership_confirmed") is True,
            "input_sent": False,
        }

    def _guard(self) -> None:
        if self.cancellation.cancelled:
            logger.debug("desktop_stage=focus_guard status=cancelled")
            raise InterruptedError("Cancelled")
        self._pg.failSafeCheck()
        if not self._window or not self._editor:
            logger.debug("desktop_stage=focus_guard status=failed reason=target_not_owned")
            raise DesktopGuardError("Open and identify Notepad first")
        foreground = self._user32.GetForegroundWindow()
        if foreground != self._window.handle:
            logger.debug("desktop_stage=focus_guard status=failed check=foreground target_hwnd=%r "
                         "foreground_hwnd=%r", self._window.handle, foreground)
            raise DesktopGuardError("Notepad lost foreground focus")
        try:
            focused = self._uia.iuia.GetFocusedElement()
            runtime_match = tuple(focused.GetRuntimeId()) == self._runtime_id
        except Exception as exc:
            logger.debug("desktop_stage=focus_guard status=failed check=uia_query exception_type=%s",
                         type(exc).__name__)
            raise
        if not runtime_match:
            logger.debug("desktop_stage=focus_guard status=failed check=editor_runtime_id")
            raise DesktopGuardError("The identified editor no longer has keyboard focus")
        if not self._editor.is_enabled() or not self._editor.is_visible():
            logger.debug("desktop_stage=focus_guard status=failed check=editor_state")
            raise DesktopGuardError("Notepad editor is unavailable")
        # Avoid shortcut injection from physically held modifiers. Do not release user keys.
        modifiers_clear = not any(self._user32.GetAsyncKeyState(key) & 0x8000
                                  for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))
        if not modifiers_clear:
            logger.debug("desktop_stage=focus_guard status=failed check=held_modifier")
            raise DesktopGuardError("Release Shift, Control, Alt and Windows keys first")
        if self._user32.GetKeyState(0x14) & 1:
            logger.debug("desktop_stage=focus_guard status=failed check=caps_lock")
            raise DesktopGuardError("Turn Caps Lock off first")
        thread_id = self._user32.GetWindowThreadProcessId(self._window.handle, None)
        # PyAutoGUI's write is not Unicode/layout-independent. Fail closed for other layouts.
        layout = self._user32.GetKeyboardLayout(thread_id) & 0xFFFFFFFF
        if layout != 0x04090409:
            logger.debug("desktop_stage=focus_guard status=failed check=keyboard_layout thread_id=%s layout=%#x",
                         thread_id, layout)
            raise DesktopGuardError("Select the standard US English keyboard layout first")
        logger.debug("desktop_stage=focus_guard status=verified foreground=true editor_runtime_id=true "
                     "enabled=true visible=true modifiers_clear=true caps_lock_off=true layout_us=true")

    def _wait_for_editor_focus(self, timeout: float = 1.0) -> None:
        """Poll read-only focus state after one activation attempt; never repeat input."""
        deadline = time.monotonic() + timeout
        poll_count = 0
        last_snapshot = (None, None, None)
        while True:
            if self.cancellation.cancelled:
                logger.debug("desktop_stage=focus_confirmation status=cancelled poll_count=%d", poll_count)
                raise InterruptedError("Cancelled")
            self._pg.failSafeCheck()
            poll_count += 1
            foreground_before_match = self._user32.GetForegroundWindow() == self._window.handle
            uia_editor_match = None
            foreground_after_match = None
            if foreground_before_match:
                try:
                    focused = self._uia.iuia.GetFocusedElement()
                    uia_editor_match = tuple(focused.GetRuntimeId()) == self._runtime_id
                    # Confirm the top-level window stayed foreground while UIA was queried.
                    foreground_after_match = self._user32.GetForegroundWindow() == self._window.handle
                except Exception as exc:
                    logger.debug("desktop_stage=focus_confirmation status=uia_query_failed poll=%d "
                                 "exception_type=%s", poll_count, type(exc).__name__)
                    raise
            last_snapshot = (foreground_before_match, uia_editor_match, foreground_after_match)
            logger.debug("desktop_stage=focus_confirmation poll=%d foreground_before_match=%s "
                         "uia_editor_runtime_match=%s foreground_after_match=%s",
                         poll_count, *last_snapshot)
            if foreground_before_match and uia_editor_match and foreground_after_match:
                logger.info("desktop_stage=focus_confirmation status=verified poll_count=%d", poll_count)
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.info("desktop_stage=focus_confirmation status=failed poll_count=%d "
                            "last_foreground_before_match=%s last_uia_editor_runtime_match=%s "
                            "last_foreground_after_match=%s", poll_count, *last_snapshot)
                raise DesktopGuardError("Notepad did not remain foreground with the identified editor focused")
            time.sleep(min(0.05, remaining))

    def _focus(self) -> None:
        self._load()
        if self._window is None or self._editor is None:
            logger.info("desktop_stage=activation status=failed reason=target_not_owned")
            raise DesktopGuardError("No owned Notepad editor")
        handle = self._window.handle
        foreground_before = self._user32.GetForegroundWindow()
        foreground_before_match = foreground_before == handle
        if foreground_before_match:
            logger.info("desktop_stage=activation status=already_foreground target_hwnd=%r", handle)
        else:
            # Desktop(backend="uia") returns UIA wrappers; their set_focus() can focus
            # an element without activating its top-level HWND. Activate the owned HWND.
            iconic = bool(self._user32.IsIconic(handle))
            show_window_return = None
            if iconic:
                show_window_return = self._user32.ShowWindow(handle, 9)  # SW_RESTORE
            set_foreground_return = self._user32.SetForegroundWindow(handle)
            foreground_after = self._user32.GetForegroundWindow()
            foreground_after_match = foreground_after == handle
            logger.info("desktop_stage=activation target_hwnd=%r foreground_before=%r "
                        "foreground_before_match=%s iconic=%s show_window_return=%r "
                        "set_foreground_return=%r foreground_after=%r foreground_after_match=%s",
                        handle, foreground_before, foreground_before_match, iconic, show_window_return,
                        set_foreground_return, foreground_after, foreground_after_match)
            if not set_foreground_return and not foreground_after_match:
                logger.info("desktop_stage=activation status=failed reason=foreground_api_refused")
                raise DesktopGuardError("Windows refused to activate the identified Notepad window")
        try:
            self._editor.set_focus()
            logger.debug("desktop_stage=editor_focus status=uia_set_focus_returned")
        except Exception as exc:
            logger.debug("desktop_stage=editor_focus status=failed exception_type=%s", type(exc).__name__)
            raise
        self._wait_for_editor_focus()

    def type_text(self, text: str) -> ToolResult:
        # Defense in depth for direct calls as well as registry calls.
        if not isinstance(text, str) or not 1 <= len(text) <= self.max_text_length:
            raise ValueError("Invalid text length")
        if any(char != "\n" and not 32 <= ord(char) <= 126 for char in text):
            raise ValueError("Unsupported character")

        try:
            self._focus()
        except DesktopGuardError as exc:
            logger.info("desktop_stage=input_delivery status=not_reached reason=focus_guard")
            return ToolResult("failed", f"Desktop safety check prevented typing: {exc}; no text was sent")
        except InterruptedError:
            logger.info("desktop_stage=input_delivery status=not_reached reason=cancelled_during_focus")
            return ToolResult("cancelled", "Typing cancelled before input; no text was sent")
        except Exception as exc:
            logger.info("desktop_stage=input_delivery status=not_reached reason=focus_exception exception_type=%s",
                        type(exc).__name__)
            return ToolResult("failed", "Could not focus and verify the agent-owned Notepad editor; "
                              "no text was sent. Check Notepad focus/accessibility before retrying")

        try:
            before = self._read(self._editor)
        except InterruptedError:
            logger.info("desktop_stage=input_delivery status=not_reached reason=cancelled_before_read")
            return ToolResult("cancelled", "Typing cancelled before input; no text was sent")
        except Exception as exc:
            logger.info("desktop_stage=input_delivery status=not_reached reason=pre_input_read_exception exception_type=%s",
                        type(exc).__name__)
            return ToolResult("failed", "Could not read Notepad before typing; no text was sent. "
                              "Inspect Notepad before retrying")

        try:
            self._guard()
            # Appending avoids overwriting selected text; this fixed shortcut is not model-selectable.
            logger.info("desktop_stage=input_delivery operation=move_caret_to_end status=started")
            self._pg.hotkey("ctrl", "end")
            logger.info("desktop_stage=input_delivery operation=move_caret_to_end status=returned")
        except DesktopGuardError as exc:
            logger.info("desktop_stage=input_delivery status=not_reached reason=guard_before_caret")
            return ToolResult("failed", f"Desktop safety check prevented typing: {exc}; no text was sent")
        except InterruptedError:
            logger.info("desktop_stage=input_delivery status=not_reached reason=cancelled_before_caret")
            return ToolResult("cancelled", "Typing cancelled before text input; no text was sent")
        except Exception as exc:
            logger.info("desktop_stage=input_delivery operation=move_caret_to_end status=failed exception_type=%s",
                        type(exc).__name__)
            return ToolResult("failed", "Could not confirm focus or move the caret in Notepad; "
                              "the requested text was not typed. Inspect before retrying")

        completed_calls = 0
        logger.info("desktop_stage=input_delivery method=PyAutoGUI status=started requested_operations=%d",
                    len(text))
        try:
            for char in text:
                self._guard()
                if char == "\n":
                    self._pg.press("enter")
                else:
                    self._pg.write(char)
                completed_calls += 1
        except DesktopGuardError as exc:
            logger.info("desktop_stage=input_delivery status=stopped completed_calls=%d reason=guard",
                        completed_calls)
            return ToolResult("failed", f"Desktop safety check stopped typing: {exc}; text may be partial. "
                              "Inspect Notepad before retrying")
        except InterruptedError:
            logger.info("desktop_stage=input_delivery status=cancelled completed_calls=%d", completed_calls)
            return ToolResult("cancelled", "Typing cancelled; text may be partial. Inspect Notepad before retrying")
        except Exception as exc:
            logger.info("desktop_stage=input_delivery status=failed completed_calls=%d exception_type=%s",
                        completed_calls, type(exc).__name__)
            return ToolResult("failed", "A keyboard input or focus check failed during typing; "
                              "text may be partial. Inspect Notepad before retrying")
        logger.info("desktop_stage=input_delivery status=returned completed_calls=%d", completed_calls)

        try:
            self._guard()
            after = self._read(self._editor)
        except DesktopGuardError as exc:
            logger.info("desktop_stage=text_verification status=not_reached reason=post_input_guard")
            return ToolResult("failed", f"Post-typing safety check failed: {exc}; inspect Notepad before retrying")
        except InterruptedError:
            logger.info("desktop_stage=text_verification status=cancelled")
            return ToolResult("cancelled", "Typing may have completed but could not be verified; "
                              "inspect Notepad before retrying")
        except Exception as exc:
            logger.info("desktop_stage=text_verification status=failed exception_type=%s", type(exc).__name__)
            return ToolResult("failed", "Text may have been entered, but final Notepad verification failed. "
                              "Inspect Notepad before retrying")

        exact_append = after == before + text
        occurrence_count = after.count(text)
        logger.info("desktop_stage=text_verification status=%s reader=controller_accessibility "
                    "before_characters=%d requested_characters=%d after_characters=%d "
                    "requested_occurrences=%d", "verified" if exact_append else "failed",
                    len(before), len(text), len(after), occurrence_count)
        if exact_append:
            return ToolResult("verified", "Exact appended text verified locally through Notepad accessibility")
        return ToolResult("failed", "Input was sent but the resulting text did not match; inspect Notepad. Do not auto-retry")

    def press_key(self, key: str) -> ToolResult:
        if not isinstance(key, str) or key not in PERMITTED_KEYS:
            raise ValueError("Key not permitted")
        self._focus()
        self._guard()
        self._pg.press(key)
        self._guard()
        return ToolResult("unverified", "Key sent to the identified editor; resulting document/caret state not verified")
