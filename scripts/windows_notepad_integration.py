"""Interactive, model-free Windows test of the real Notepad controller.

Run explicitly with: .venv\\Scripts\\python.exe scripts\\windows_notepad_integration.py
This is not collected by pytest and never saves or closes the test document.
"""
import json
import logging
import os
from pathlib import Path
import sys
import warnings
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safety import Cancellation
from windows_controller import WindowsController


EDIT_CONTROL_TYPES = {"Edit", "Document"}
EDIT_CLASS_NAMES = {"Edit", "RichEditD2DPT"}


def report(event: str, **fields) -> None:
    print("DIAGNOSTIC " + json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def report_warnings(stage: str, captured, redactions=()) -> None:
    for warning in captured:
        fields = {
            "stage": stage,
            "category": warning.category.__name__,
            "source": Path(warning.filename).name,
            "line": warning.lineno,
        }
        # ResourceWarning text is useful for diagnosing process/handle lifetime.
        # Other warning messages are omitted so diagnostics cannot expose UI text.
        if issubclass(warning.category, ResourceWarning):
            message = str(warning.message)
            for secret in redactions:
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            fields["message"] = message[:512]
            fields["message_truncated"] = len(message) > 512
        report("python_warning", **fields)


def approve(action: str) -> bool:
    try:
        answer = input(f"{action} Type yes to approve this action: ")
    except EOFError:
        return False
    return answer.strip().lower() == "yes"


def target_snapshot(controller: WindowsController) -> None:
    window = controller._window
    editor = controller._editor
    foreground = controller._user32.GetForegroundWindow()
    try:
        focused = controller._uia.iuia.GetFocusedElement()
        focused_matches = tuple(focused.GetRuntimeId()) == controller._runtime_id
        focus_probe_exception = None
    except Exception as exc:
        focused_matches = None
        focus_probe_exception = type(exc).__name__
    info = window.element_info
    editor_info = editor.element_info
    report(
        "identified_target",
        hwnd=hex(int(window.handle)),
        window_class=info.class_name,
        process_id=info.process_id,
        launched_process_id=controller._launched_process_id,
        target_pid_matches_launch=info.process_id == controller._launched_process_id,
        target_ownership_basis=controller._window_ownership_basis,
        target_ownership_confirmed=controller._window_ownership_basis in {
            "launch_pid_match", "verified_direct_child"},
        editor_class=editor_info.class_name,
        editor_control_type=editor_info.control_type,
        editor_visible=bool(editor.is_visible()),
        editor_enabled=bool(editor.is_enabled()),
        foreground_hwnd=hex(int(foreground)) if foreground else None,
        foreground_matches_target=foreground == window.handle,
        focused_editor_matches=focused_matches,
        focus_probe_exception_type=focus_probe_exception,
    )


def independently_verify_text(controller: WindowsController, expected: str) -> bool:
    """Re-find the owned editor and read it through a fresh UIA TextPattern object."""
    from pywinauto import Desktop

    hwnd = int(controller._window.handle)
    try:
        window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        editors = [item for item in window.descendants()
                   if item.element_info.control_type in EDIT_CONTROL_TYPES
                   and item.element_info.class_name in EDIT_CLASS_NAMES
                   and item.is_visible() and item.is_enabled()]
    except Exception as exc:
        report("independent_text_verification", status="failed", stage="editor_rediscovery",
               exception_type=type(exc).__name__)
        return False
    if len(editors) != 1:
        report("independent_text_verification", status="failed", stage="editor_rediscovery",
               editor_count=len(editors))
        return False
    try:
        runtime_matches = (tuple(editors[0].element_info.element.GetRuntimeId())
                           == controller._runtime_id)
    except Exception as exc:
        report("independent_text_verification", status="failed", stage="editor_identity",
               exception_type=type(exc).__name__)
        return False
    if not runtime_matches:
        report("independent_text_verification", status="failed", stage="editor_identity",
               runtime_id_matches_controller=False)
        return False

    try:
        # TextPattern is queried on a new Desktop/wrapper. Never print document contents.
        document = editors[0].iface_text.DocumentRange.GetText(-1)
        document = document.replace("\r\n", "\n").replace("\r", "\n")
    except Exception as exc:
        report("independent_text_verification", status="failed", stage="uia_text_pattern",
               exception_type=type(exc).__name__)
        return False

    occurrences = document.count(expected)
    exact_document = document == expected
    passed = exact_document and occurrences == 1
    report(
        "independent_text_verification",
        status="passed" if passed else "failed",
        method="fresh_UIA_TextPattern",
        runtime_id_matches_controller=runtime_matches,
        document_character_count=len(document),
        expected_character_count=len(expected),
        exact_document_match=exact_document,
        expected_occurrence_count=occurrences,
    )
    return passed


def run() -> int:
    if os.name != "nt":
        report("environment", status="failed", reason="Windows is required")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("windows_controller").setLevel(logging.DEBUG)
    cancellation = Cancellation()
    controller = WindowsController(
        launch_timeout=20.0, cancellation=cancellation, process_diagnostics=True)

    if not approve("Launch and identify one new blank Notepad window?"):
        report("window_discovery", status="denied", action_executed=False)
        return 2
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        opened = controller.open_notepad()
    report_warnings("open_notepad", caught)
    report("open_notepad", status=opened.status, message=opened.message)
    relationship = controller._last_process_relationship_diagnostics
    if relationship is not None:
        report("process_relationship_diagnostics", **relationship)
    if opened.status != "verified":
        failed_stage = ("window_process_ownership"
                        if relationship is not None and not relationship.get("ownership_confirmed")
                        else "window_discovery_or_editor_identification")
        report("result", status="failed", failed_stage=failed_stage)
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        target_snapshot(controller)
    report_warnings("target_snapshot", caught)
    expected = "da-integration-" + uuid4().hex[:12]
    if not approve(f"Type the harmless unique string {expected!r} into that identified editor?"):
        report("input_delivery", status="denied", action_executed=False)
        return 2

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            typed = controller.type_text(expected)
    except KeyboardInterrupt:
        report("input_delivery", status="cancelled", inspect_notepad_for_partial_input=True)
        return 130
    except Exception as exc:
        report("input_delivery", status="failed", exception_type=type(exc).__name__,
               inspect_notepad_for_partial_input=True)
        return 1
    report_warnings("type_text", caught, redactions=(expected,))

    report("controller_type_text", status=typed.status, message=typed.message)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        verified = independently_verify_text(controller, expected)
    report_warnings("independent_text_verification", caught, redactions=(expected,))
    passed = typed.status == "verified" and verified
    report("result", status="passed" if passed else "failed",
           controller_verified=typed.status == "verified", independent_verified=verified,
           inspect_notepad=True)
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        report("cancelled", inspect_notepad_for_partial_input=True)
        raise SystemExit(130)
    except Exception as exc:
        report("uncaught", status="failed", exception_type=type(exc).__name__)
        raise SystemExit(1)
