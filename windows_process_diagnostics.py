"""Best-effort, read-only Windows process identity and parentage diagnostics.

These snapshots are for troubleshooting only. They never authorize a window,
input, or process action.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Iterable


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
ERROR_NO_MORE_FILES = 18


def capture_process_hierarchy(pids: Iterable[int], max_ancestors: int = 5) -> dict[str, Any]:
    """Capture the named processes and a bounded parent chain using read-only Win32 APIs."""
    requested: list[int] = []
    for pid in pids:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
            continue
        if pid not in requested:
            requested.append(pid)

    if max_ancestors < 0 or max_ancestors > 16:
        return {
            "status": "error",
            "reason": "invalid_ancestor_limit",
            "requested_pids": requested,
            "processes": {},
            "chains": {},
        }
    if os.name != "nt":
        return {
            "status": "unavailable",
            "reason": "windows_required",
            "requested_pids": requested,
            "processes": {},
            "chains": {},
        }

    try:
        return _capture_windows_process_hierarchy(requested, max_ancestors)
    except Exception as exc:  # Diagnostics must not interfere with the fail-closed guard.
        return {
            "status": "error",
            "exception_type": type(exc).__name__,
            "requested_pids": requested,
            "processes": {},
            "chains": {},
        }


def capture_process_handle_identity(process_handle: Any, expected_pid: int) -> dict[str, Any]:
    """Read identity and lifetime timestamps from a Popen-owned Windows process handle."""
    if os.name != "nt":
        return {"status": "unavailable", "reason": "windows_required", "pid": expected_pid}
    try:
        handle_value = int(process_handle)
    except (TypeError, ValueError, OverflowError):
        return {"status": "error", "reason": "invalid_process_handle", "pid": expected_pid}
    if handle_value <= 0:
        return {"status": "error", "reason": "invalid_process_handle", "pid": expected_pid}

    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel32.GetProcessId.restype = wintypes.DWORD
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL

    actual_pid = int(kernel32.GetProcessId(handle_value))
    if actual_pid == 0:
        return {
            "status": "error",
            "reason": "get_process_id_failed",
            "pid": expected_pid,
            "winerror": ctypes.get_last_error(),
        }
    result: dict[str, Any] = {"pid": actual_pid, "expected_pid": expected_pid}
    if actual_pid != expected_pid:
        result.update(status="error", reason="process_handle_pid_mismatch")
        return result

    image_buffer = ctypes.create_unicode_buffer(32768)
    image_length = wintypes.DWORD(len(image_buffer))
    if kernel32.QueryFullProcessImageNameW(
            handle_value, 0, image_buffer, ctypes.byref(image_length)):
        result.update(image_path=image_buffer.value, image_path_status="read")
    else:
        result.update(image_path_status="unavailable", image_path_winerror=ctypes.get_last_error())

    creation = FILETIME()
    exit_time = FILETIME()
    kernel_time = FILETIME()
    user_time = FILETIME()
    if kernel32.GetProcessTimes(
            handle_value,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time)):
        creation_ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        exit_ticks = (int(exit_time.dwHighDateTime) << 32) | int(exit_time.dwLowDateTime)
        result.update(
            creation_time_filetime_100ns=str(creation_ticks),
            creation_time_utc=_filetime_to_utc(creation_ticks),
            exit_time_filetime_100ns=str(exit_ticks) if exit_ticks else None,
            exit_time_utc=_filetime_to_utc(exit_ticks) if exit_ticks else None,
            process_is_running=not bool(exit_ticks),
            process_times_status="read",
        )
    else:
        result.update(process_times_status="unavailable", process_times_winerror=ctypes.get_last_error())
    result["status"] = ("ok" if result.get("image_path_status") == "read"
                        and result.get("process_times_status") == "read" else "partial")
    return result


def _capture_windows_process_hierarchy(pids: list[int], max_ancestors: int) -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot_handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot_handle is None or snapshot_handle == invalid_handle:
        return {
            "status": "error",
            "reason": "process_snapshot_failed",
            "winerror": ctypes.get_last_error(),
            "requested_pids": pids,
            "processes": {},
            "chains": {},
        }

    entries: dict[int, dict[str, Any]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        has_entry = bool(kernel32.Process32FirstW(snapshot_handle, ctypes.byref(entry)))
        while has_entry:
            pid = int(entry.th32ProcessID)
            entries[pid] = {
                "pid": pid,
                "parent_pid": int(entry.th32ParentProcessID),
                "image_name": str(entry.szExeFile),
            }
            has_entry = bool(kernel32.Process32NextW(snapshot_handle, ctypes.byref(entry)))
        enumeration_error = ctypes.get_last_error()
    finally:
        kernel32.CloseHandle(snapshot_handle)

    detail_cache: dict[int, dict[str, Any]] = {}

    def process_detail(pid: int) -> dict[str, Any]:
        if pid in detail_cache:
            return detail_cache[pid]
        entry = entries.get(pid)
        if entry is None:
            detail = {"pid": pid, "status": "not_in_snapshot"}
            detail_cache[pid] = detail
            return detail

        detail = {"status": "present", **entry}
        process_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process_handle:
            detail["query_status"] = "open_process_failed"
            detail["query_winerror"] = ctypes.get_last_error()
            detail_cache[pid] = detail
            return detail

        try:
            image_buffer = ctypes.create_unicode_buffer(32768)
            image_length = wintypes.DWORD(len(image_buffer))
            if kernel32.QueryFullProcessImageNameW(
                    process_handle, 0, image_buffer, ctypes.byref(image_length)):
                detail["image_path"] = image_buffer.value
                detail["image_path_status"] = "read"
            else:
                detail["image_path_status"] = "unavailable"
                detail["image_path_winerror"] = ctypes.get_last_error()

            creation = FILETIME()
            exit_time = FILETIME()
            kernel_time = FILETIME()
            user_time = FILETIME()
            if kernel32.GetProcessTimes(
                    process_handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time)):
                creation_ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                exit_ticks = (int(exit_time.dwHighDateTime) << 32) | int(exit_time.dwLowDateTime)
                detail["creation_time_filetime_100ns"] = str(creation_ticks)
                detail["creation_time_utc"] = _filetime_to_utc(creation_ticks)
                detail["exit_time_filetime_100ns"] = str(exit_ticks) if exit_ticks else None
                detail["exit_time_utc"] = _filetime_to_utc(exit_ticks) if exit_ticks else None
                detail["process_is_running"] = not bool(exit_ticks)
                detail["creation_time_status"] = "read"
            else:
                detail["creation_time_status"] = "unavailable"
                detail["creation_time_winerror"] = ctypes.get_last_error()
        finally:
            kernel32.CloseHandle(process_handle)

        detail_cache[pid] = detail
        return detail

    chains: dict[str, list[dict[str, Any]]] = {}
    processes: dict[str, dict[str, Any]] = {}
    for root_pid in pids:
        chain: list[dict[str, Any]] = []
        seen: set[int] = set()
        current_pid = root_pid
        current = process_detail(current_pid)
        for _ in range(max_ancestors + 1):
            if current_pid in seen:
                chain.append({"pid": current_pid, "status": "cycle_detected"})
                break
            seen.add(current_pid)
            chain.append(current)
            if current.get("status") != "present":
                break
            parent_pid = current.get("parent_pid")
            if not isinstance(parent_pid, int) or parent_pid <= 0 or parent_pid == current_pid:
                break
            current_pid = parent_pid
            current = process_detail(current_pid)
        else:
            chain.append({"pid": current_pid, "status": "ancestor_limit_reached"})

        # Toolhelp records a parent PID, but that PID may have been reused after
        # the child was created. Compare creation times before treating it as ancestry.
        chain = [dict(record) for record in chain]
        for depth in range(1, len(chain)):
            child, parent = chain[depth - 1], chain[depth]
            if parent.get("status") == "not_in_snapshot":
                parent["parent_link_status"] = "pid_observed_process_not_in_snapshot"
                chain = chain[:depth + 1]
                break
            if parent.get("status") != "present":
                parent["parent_link_status"] = parent.get("status", "unavailable")
                chain = chain[:depth + 1]
                break
            child_time = _creation_ticks(child)
            parent_time = _creation_ticks(parent)
            if child_time is None or parent_time is None:
                parent["parent_link_status"] = "creation_time_unavailable"
            elif parent_time > child_time:
                parent["status"] = "pid_reused_after_child"
                parent["parent_link_status"] = "parent_created_after_child"
                chain = chain[:depth + 1]
                break
            else:
                parent["parent_link_status"] = "creation_time_consistent"
        chains[str(root_pid)] = chain
        processes[str(root_pid)] = chain[0] if chain else {"pid": root_pid, "status": "not_in_snapshot"}

    found_all_roots = all(processes.get(str(pid), {}).get("status") == "present" for pid in pids)
    status = "ok" if found_all_roots else "partial"
    result: dict[str, Any] = {
        "status": status,
        "method": "Toolhelp32Snapshot+QueryFullProcessImageNameW+GetProcessTimes",
        "requested_pids": pids,
        "processes": processes,
        "chains": chains,
    }
    if not entries and enumeration_error not in (0, ERROR_NO_MORE_FILES):
        result["enumeration_winerror"] = enumeration_error
    return result


def summarize_process_relationship(
        launch_pid: int,
        window_pid: int,
        launch_at_start: dict[str, Any],
        current_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Summarize PID, image, and ancestry evidence without making an ownership decision."""
    launch_key = str(launch_pid)
    window_key = str(window_pid)
    launch_chain = _get_chain(launch_at_start, launch_key) or _get_chain(current_snapshot, launch_key)
    window_chain = _get_chain(current_snapshot, window_key)
    # Only the immediate launch snapshot can identify which process instance was
    # created by Popen. A later process with a reused PID is not treated as it.
    launch_record_at_start = _get_process(launch_at_start, launch_key)
    launch_record_current = _get_process(current_snapshot, launch_key)
    window_record = _get_process(current_snapshot, window_key)

    window_launch_ancestor_depth = _ancestor_depth(window_chain, launch_pid)
    launch_window_ancestor_depth = _ancestor_depth(launch_chain, window_pid)
    launch_ancestors = {
        record["pid"]: (depth, record)
        for depth, record in enumerate(launch_chain[1:], start=1)
        if isinstance(record.get("pid"), int) and record.get("status") == "present"
    }
    window_ancestors = {
        record["pid"]: (depth, record)
        for depth, record in enumerate(window_chain[1:], start=1)
        if isinstance(record.get("pid"), int) and record.get("status") == "present"
    }
    common_pids = sorted(set(launch_ancestors) & set(window_ancestors))
    shared_ancestor_evidence = []
    for pid in common_pids:
        launch_depth, launch_ancestor = launch_ancestors[pid]
        window_depth, window_ancestor = window_ancestors[pid]
        same_instance = _same_process_instance(launch_ancestor, window_ancestor)
        launch_path_valid = _parent_chain_status(launch_chain, launch_depth)
        window_path_valid = _parent_chain_status(window_chain, window_depth)
        shared_ancestor_evidence.append({
            "pid": pid,
            "same_process_instance": same_instance,
            "launch_parent_chain_time_order_verified": launch_path_valid,
            "window_parent_chain_time_order_verified": window_path_valid,
        })
    shared_ancestor_pids = [
        item["pid"] for item in shared_ancestor_evidence
        if item["same_process_instance"] is True
        and item["launch_parent_chain_time_order_verified"] is True
        and item["window_parent_chain_time_order_verified"] is True
    ]
    unconfirmed_shared_ancestor_pids = [
        item["pid"] for item in shared_ancestor_evidence
        if item["same_process_instance"] is not False
        and (item["launch_parent_chain_time_order_verified"] is not True
             or item["window_parent_chain_time_order_verified"] is not True)
    ]

    launch_image_at_start = launch_record_at_start.get("image_path") if launch_record_at_start else None
    launch_image_current = launch_record_current.get("image_path") if launch_record_current else None
    window_image = window_record.get("image_path") if window_record else None
    same_image = None
    if isinstance(launch_image_at_start, str) and isinstance(window_image, str):
        same_image = launch_image_at_start.casefold() == window_image.casefold()

    window_ancestry_order = (
        _parent_chain_status(window_chain, window_launch_ancestor_depth)
        if window_launch_ancestor_depth is not None else None
    )
    launch_ancestry_order = (
        _parent_chain_status(launch_chain, launch_window_ancestor_depth)
        if launch_window_ancestor_depth is not None else None
    )
    if window_launch_ancestor_depth is not None:
        chain_record = window_chain[window_launch_ancestor_depth]
        identity_match = _same_process_instance(launch_record_at_start, chain_record)
        if identity_match is True and window_ancestry_order is True:
            classification = ("window_direct_child_of_launch" if window_launch_ancestor_depth == 1
                              else "window_descendant_of_launch")
        elif identity_match is False:
            classification = "launch_pid_reuse_or_ambiguous_ancestry"
        elif identity_match is True:
            classification = "launch_pid_identity_matches_but_parentage_time_order_unverified"
        else:
            classification = "launch_pid_in_window_ancestry_identity_unconfirmed"
    elif launch_window_ancestor_depth is not None:
        chain_record = launch_chain[launch_window_ancestor_depth]
        identity_match = _same_process_instance(window_record, chain_record)
        if identity_match is True and launch_ancestry_order is True:
            classification = ("launch_direct_child_of_window" if launch_window_ancestor_depth == 1
                              else "launch_descendant_of_window")
        elif identity_match is False:
            classification = "window_pid_reuse_or_ambiguous_ancestry"
        elif identity_match is True:
            classification = "window_pid_identity_matches_but_parentage_time_order_unverified"
        else:
            classification = "window_pid_in_launch_ancestry_identity_unconfirmed"
    elif shared_ancestor_pids:
        classification = "shared_ancestor_only"
    elif unconfirmed_shared_ancestor_pids:
        classification = "possible_shared_ancestor_identity_unconfirmed"
    elif same_image is True:
        classification = "same_image_without_observed_parent_link"
    elif same_image is False:
        classification = "different_images_without_observed_parent_link"
    else:
        classification = "insufficient_identity_or_ancestry_data"

    return {
        "classification": classification,
        "launch_pid": launch_pid,
        "window_pid": window_pid,
        "window_parent_chain_contains_launch_pid": window_launch_ancestor_depth is not None,
        "window_ancestor_depth_for_launch_pid": window_launch_ancestor_depth,
        "window_ancestor_identity_matches_launch_snapshot": (
            _same_process_instance(launch_record_at_start,
                                   window_chain[window_launch_ancestor_depth])
            if window_launch_ancestor_depth is not None else None
        ),
        "window_parent_chain_time_order_verified": window_ancestry_order,
        "launch_parent_chain_contains_window_pid": launch_window_ancestor_depth is not None,
        "launch_ancestor_depth_for_window_pid": launch_window_ancestor_depth,
        "launch_ancestor_identity_matches_window_snapshot": (
            _same_process_instance(window_record, launch_chain[launch_window_ancestor_depth])
            if launch_window_ancestor_depth is not None else None
        ),
        "launch_parent_chain_time_order_verified": launch_ancestry_order,
        "shared_ancestor_pids": shared_ancestor_pids,
        "possible_shared_ancestor_pids": unconfirmed_shared_ancestor_pids,
        "shared_ancestor_evidence": shared_ancestor_evidence,
        "launch_image_path_at_start": launch_image_at_start,
        "launch_image_path_current": launch_image_current,
        "window_image_path": window_image,
        "image_paths_equal": same_image,
        "ownership_confirmed": False,
    }


def verify_direct_launch_child(
        launch_pid: int,
        window_pid: int,
        launch_handle_identity: dict[str, Any],
        current_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Confirm only a direct Notepad child whose parent instance is the Popen process.

    A PID link alone is insufficient. The Popen-owned handle must still identify the
    launched PID, its image must match the visible-window process, creation times must
    be ordered, and the Popen process must not have exited before the window child.
    """
    window = _get_process(current_snapshot, str(window_pid))
    launch_path = launch_handle_identity.get("image_path")
    window_path = window.get("image_path") if window else None
    launch_creation = _creation_ticks(launch_handle_identity)
    window_creation = _creation_ticks(window) if window else None
    launch_exit_raw = launch_handle_identity.get("exit_time_filetime_100ns")
    try:
        launch_exit = int(launch_exit_raw) if launch_exit_raw is not None else None
    except (TypeError, ValueError):
        launch_exit = None

    process_handle_pid = launch_handle_identity.get("pid")
    checks = {
        "popen_handle_pid_matches_launch": (
            process_handle_pid == launch_pid
            and launch_handle_identity.get("expected_pid", launch_pid) == launch_pid
        ),
        "window_process_present": window is not None,
        "window_parent_pid_matches_launch": (
            window.get("parent_pid") == launch_pid if window else False
        ),
        "same_executable_image": (
            launch_path.casefold() == window_path.casefold()
            if isinstance(launch_path, str) and isinstance(window_path, str) else None
        ),
        "launch_created_before_window": (
            launch_creation < window_creation
            if launch_creation is not None and window_creation is not None else None
        ),
        "launch_alive_at_window_creation": (
            launch_exit == 0 or launch_exit is None
            if launch_handle_identity.get("process_is_running") is True
            else (launch_exit > window_creation
                  if launch_exit is not None and window_creation is not None else None)
        ),
    }
    verified = all(value is True for value in checks.values())
    if verified:
        classification = "verified_direct_launch_child"
    elif any(value is False for value in checks.values()):
        classification = "direct_launch_child_not_verified"
    else:
        classification = "direct_launch_child_evidence_incomplete"
    return {
        "classification": classification,
        "launch_pid": launch_pid,
        "window_pid": window_pid,
        "launch_image_path": launch_path,
        "window_image_path": window_path,
        "window_parent_pid": window.get("parent_pid") if window else None,
        "launch_creation_time_filetime_100ns": (
            str(launch_creation) if launch_creation is not None else None
        ),
        "launch_exit_time_filetime_100ns": (
            str(launch_exit) if launch_exit is not None else None
        ),
        "window_creation_time_filetime_100ns": (
            str(window_creation) if window_creation is not None else None
        ),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if passed is not True],
        "ownership_confirmed": verified,
    }


def _get_chain(snapshot: dict[str, Any], pid_key: str) -> list[dict[str, Any]]:
    chains = snapshot.get("chains", {})
    chain = chains.get(pid_key, []) if isinstance(chains, dict) else []
    return chain if isinstance(chain, list) else []


def _get_process(snapshot: dict[str, Any], pid_key: str) -> dict[str, Any] | None:
    processes = snapshot.get("processes", {})
    if isinstance(processes, dict):
        record = processes.get(pid_key)
        if isinstance(record, dict) and record.get("status") == "present":
            return record
    for record in _get_chain(snapshot, pid_key):
        if isinstance(record, dict) and record.get("status") == "present":
            return record
    return None


def _filetime_to_utc(ticks: int) -> str | None:
    try:
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        return (epoch + timedelta(microseconds=ticks // 10)).isoformat()
    except (OverflowError, ValueError):
        return None


def _creation_ticks(record: dict[str, Any]) -> int | None:
    try:
        return int(record["creation_time_filetime_100ns"])
    except (KeyError, TypeError, ValueError):
        return None


def _parent_chain_status(chain: list[dict[str, Any]], depth: int) -> bool | None:
    """True only when every parent edge through depth has time-consistent identity."""
    statuses = [chain[index].get("parent_link_status") for index in range(1, depth + 1)]
    if statuses and all(status == "creation_time_consistent" for status in statuses):
        return True
    if "parent_created_after_child" in statuses:
        return False
    return None


def _ancestor_depth(chain: list[dict[str, Any]], pid: int) -> int | None:
    # A parent PID still supplies a relationship clue if that process has exited
    # and is absent from the snapshot. Identity then remains explicitly unconfirmed.
    for depth, record in enumerate(chain[1:], start=1):
        if record.get("pid") == pid and record.get("status") in {"present", "not_in_snapshot"}:
            return depth
    return None


def _same_process_instance(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool | None:
    if not left or not right:
        return None
    left_creation = left.get("creation_time_filetime_100ns")
    right_creation = right.get("creation_time_filetime_100ns")
    if left_creation is None or right_creation is None:
        return None
    return str(left_creation) == str(right_creation)
