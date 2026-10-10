import json
import warnings
from types import SimpleNamespace

from scripts.windows_notepad_integration import report_warnings
import windows_process_diagnostics as process_diagnostics
from windows_process_diagnostics import (
    capture_process_handle_identity,
    capture_process_hierarchy,
    summarize_process_relationship,
    verify_direct_launch_child,
)


def _record(pid, parent_pid, image_path, creation_time):
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "status": "present",
        "image_name": image_path.rsplit("\\", 1)[-1],
        "image_path": image_path,
        "creation_time_filetime_100ns": str(creation_time),
    }


def _snapshot(chains):
    return {
        "status": "ok",
        "processes": {str(pid): chain[0] for pid, chain in chains.items()},
        "chains": {str(pid): chain for pid, chain in chains.items()},
    }


def _launch_handle(
        exit_time="300", running=False, image_path=r"C:\Windows\System32\notepad.exe",
        creation_time="100"):
    return {
        "status": "ok",
        "pid": 42,
        "expected_pid": 42,
        "image_path": image_path,
        "creation_time_filetime_100ns": creation_time,
        "exit_time_filetime_100ns": exit_time,
        "process_is_running": running,
    }


def test_verified_direct_child_requires_same_image_parent_pid_and_live_time_order():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    current = _snapshot({99: [window]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["classification"] == "verified_direct_launch_child"
    assert result["ownership_confirmed"] is True
    assert all(result["checks"].values())


def test_image_uses_launch_time_path_only_when_handle_creation_time_matches():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    current = _snapshot({99: [window]})
    launch_at_start = _launch_handle(exit_time=None, running=True)
    launch_at_mismatch = _launch_handle(
        exit_time="300", running=False, image_path=None)

    result = verify_direct_launch_child(
        42, 99, launch_at_mismatch, current, launch_at_start)

    assert result["classification"] == "verified_direct_launch_child"
    assert result["launch_image_source"] == "popen_handle_at_start_same_creation_time"
    assert result["checks"]["popen_handle_matches_start_identity"] is True


def test_launch_time_image_fallback_still_requires_matching_window_image():
    window = _record(99, 42, r"C:\Windows\System32\mspaint.exe", 200)
    current = _snapshot({99: [window]})
    launch_at_start = _launch_handle(exit_time=None, running=True)
    launch_at_mismatch = _launch_handle(
        exit_time="300", running=False, image_path=None)

    result = verify_direct_launch_child(
        42, 99, launch_at_mismatch, current, launch_at_start)

    assert result["ownership_confirmed"] is False
    assert result["checks"]["popen_handle_matches_start_identity"] is True
    assert result["checks"]["same_executable_image"] is False


def test_launch_time_image_is_not_reused_after_a_popen_handle_pid_reuse():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    current = _snapshot({99: [window]})
    launch_at_start = _launch_handle(exit_time=None, running=True, creation_time="100")
    launch_at_mismatch = _launch_handle(
        exit_time="300", running=False, image_path=None, creation_time="150")

    result = verify_direct_launch_child(
        42, 99, launch_at_mismatch, current, launch_at_start)

    assert result["ownership_confirmed"] is False
    assert result["checks"]["popen_handle_matches_start_identity"] is False
    assert result["launch_image_path"] is None


def test_direct_child_rejected_if_window_creation_precedes_launch_creation():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 90)
    current = _snapshot({99: [window]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["ownership_confirmed"] is False
    assert result["checks"]["launch_created_before_window"] is False


def test_direct_child_rejected_if_launch_process_exited_before_window_creation():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    current = _snapshot({99: [window]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(exit_time="150"), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["ownership_confirmed"] is False
    assert result["checks"]["launch_alive_at_window_creation"] is False
    assert "launch_alive_at_window_creation" in result["failed_checks"]


def test_indirect_descendant_is_not_accepted_as_a_direct_child():
    window = _record(99, 77, r"C:\Windows\System32\notepad.exe", 200)
    intermediate = _record(77, 42, r"C:\Windows\System32\notepad.exe", 150)
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 100)
    current = _snapshot({99: [window, intermediate, launch]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["ownership_confirmed"] is False
    assert result["checks"]["window_parent_pid_matches_launch"] is False


def test_direct_child_rejected_when_parent_exit_time_is_ambiguous_at_child_creation():
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    current = _snapshot({99: [window]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(exit_time="200"), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["ownership_confirmed"] is False
    assert result["checks"]["launch_alive_at_window_creation"] is False


def test_direct_child_rejected_when_parent_pid_or_image_does_not_match():
    window = _record(99, 77, r"C:\Windows\System32\\notepad.exe", 200)
    current = _snapshot({99: [window]})

    result = verify_direct_launch_child(
        42, 99, _launch_handle(), current,
        _launch_handle(exit_time=None, running=True),
    )

    assert result["ownership_confirmed"] is False
    assert result["checks"]["window_parent_pid_matches_launch"] is False


def test_capture_is_explicitly_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(process_diagnostics, "os", SimpleNamespace(name="posix"))
    result = capture_process_hierarchy((123, 456))

    assert result["status"] == "unavailable"
    assert result["reason"] == "windows_required"
    assert result["requested_pids"] == [123, 456]
    assert capture_process_handle_identity(123, 123)["status"] == "unavailable"


def test_relationship_reports_direct_parent_evidence_without_approving_ownership():
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 100)
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    launch_at_start = _snapshot({42: [launch]})
    launch_parent = {**launch, "parent_link_status": "creation_time_consistent"}
    current = _snapshot({42: [launch], 99: [window, launch_parent]})

    result = summarize_process_relationship(42, 99, launch_at_start, current)

    assert result["classification"] == "window_direct_child_of_launch"
    assert result["window_parent_chain_contains_launch_pid"] is True
    assert result["window_ancestor_identity_matches_launch_snapshot"] is True
    assert result["image_paths_equal"] is True
    assert result["ownership_confirmed"] is False


def test_pid_reuse_is_not_misreported_as_a_launch_handoff():
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 100)
    reused_launch_pid = _record(42, 10, r"C:\Windows\System32\notepad.exe", 300)
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 400)
    launch_at_start = _snapshot({42: [launch]})
    current = _snapshot({42: [reused_launch_pid], 99: [window, reused_launch_pid]})

    result = summarize_process_relationship(42, 99, launch_at_start, current)

    assert result["classification"] == "launch_pid_reuse_or_ambiguous_ancestry"
    assert result["window_ancestor_identity_matches_launch_snapshot"] is False
    assert result["ownership_confirmed"] is False


def test_parent_pid_link_is_reported_but_not_confirmed_when_launch_process_exited():
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 100)
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    launch_at_start = _snapshot({42: [launch]})
    current = {
        "status": "partial",
        "processes": {
            "42": {"pid": 42, "status": "not_in_snapshot"},
            "99": window,
        },
        "chains": {
            "42": [{"pid": 42, "status": "not_in_snapshot"}],
            "99": [window, {"pid": 42, "status": "not_in_snapshot"}],
        },
    }

    result = summarize_process_relationship(42, 99, launch_at_start, current)

    assert result["classification"] == "launch_pid_in_window_ancestry_identity_unconfirmed"
    assert result["window_parent_chain_contains_launch_pid"] is True
    assert result["window_ancestor_identity_matches_launch_snapshot"] is None
    assert result["ownership_confirmed"] is False


def test_pid_reused_after_window_creation_is_not_counted_as_its_parent():
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 300)
    window = _record(99, 42, r"C:\Windows\System32\notepad.exe", 200)
    parent_pid_reuse = {
        **launch,
        "status": "pid_reused_after_child",
        "parent_link_status": "parent_created_after_child",
    }
    launch_at_start = _snapshot({42: [launch]})
    current = _snapshot({99: [window, parent_pid_reuse]})

    result = summarize_process_relationship(42, 99, launch_at_start, current)

    assert result["window_parent_chain_contains_launch_pid"] is False
    assert result["classification"] == "same_image_without_observed_parent_link"
    assert result["ownership_confirmed"] is False


def test_same_image_without_parentage_is_not_enough_to_confirm_handoff():
    launch = _record(42, 10, r"C:\Windows\System32\notepad.exe", 100)
    window = _record(99, 11, r"C:\Windows\System32\notepad.exe", 200)
    launch_at_start = _snapshot({42: [launch, _record(10, 1, r"C:\Windows\System32\explorer.exe", 50)]})
    current = _snapshot({
        99: [window, _record(11, 2, r"C:\Windows\System32\explorer.exe", 60)],
    })

    result = summarize_process_relationship(42, 99, launch_at_start, current)

    assert result["classification"] == "same_image_without_observed_parent_link"
    assert result["image_paths_equal"] is True
    assert result["ownership_confirmed"] is False


def test_resource_warning_report_includes_message_and_source_but_redacts_test_text(capsys):
    test_text = "da-integration-sensitive"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        warnings.warn(f"subprocess 360 is still running: {test_text}", ResourceWarning)

    report_warnings("open_notepad", captured, redactions=(test_text,))

    event = json.loads(capsys.readouterr().out.removeprefix("DIAGNOSTIC "))
    assert event["event"] == "python_warning"
    assert event["category"] == "ResourceWarning"
    assert event["stage"] == "open_notepad"
    assert "subprocess 360 is still running" in event["message"]
    assert test_text not in event["message"]
    assert event["source"] == "test_windows_process_diagnostics.py"
    assert isinstance(event["line"], int)
