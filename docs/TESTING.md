# Testing

Run `python -m pytest -q` from the repository root. Automated tests never call
real desktop APIs or require Ollama. Fixtures inject mocked controllers/clients;
adapter tests replace focus, keyboard and readback dependencies. Transport tests
replace the HTTP opener, including unavailable-service and malformed responses.

Coverage includes unknown tools, strict arguments, unsupported text/keys,
mandatory approval, cancellation including Ctrl+C at approval, repeated actions,
bounded steps, accurate failure/unverified reporting, native tool-call request/
response parsing, rejection of malformed calls, bounded re-prompt and safe stop
for multiple calls, connection/timeout/HTTP-status/truncated-response handling,
local-only configuration, missing-model guidance, exact append verification,
verbatim-text prompt checks, direct-request text correction before approval,
launched-process PID ownership checks, mocked Win32 foreground activation and
bounded focus confirmation, sanitized
focus/input/verification failure messages,
and a mocked Notepad workflow. INFO logs record
each planner response's wall-clock latency/type and tool name/status without
task text or tool arguments; these timings become meaningful model measurements
only when run against the actual local Ollama service.

## Live model-free Windows test

Before using the planner, run this explicit integration test from the repository
root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\windows_notepad_integration.py
```

It imports only the existing controller, asks for separate approval to launch a
fresh blank Notepad and type one unique harmless string, then independently
re-discovers the editor and verifies the exact full document once through a fresh
UIA `TextPattern` reader. It does not call Ollama/the planner, save, or close the
window. Its diagnostics report stage names, HWND/class/process identifiers,
foreground API outcomes, UIA focus-match booleans, input-call counts and verification
counts. If launch and window PIDs differ, the test reports the Popen-handle
identity/lifetime, executable image, creation/exit timestamps, HWND/class and bounded
parent chains. A different PID is accepted only when the window process is a **direct
child** of the Popen process, the Popen handle still identifies the launched PID, the
image paths match, and the parent was alive at the child's creation time. Missing or
contradictory evidence fails closed before editor traversal. The accepted window must
still contain one blank accessible editor, and typing still requires separate
approval. Document contents, window titles and exception messages are not logged.
`ResourceWarning` messages include source location; the unique test string is
redacted from warning text. Executable paths may include local account/profile names.
Inspect the open document before closing it. If the test fails, retain its stage logs
and do not blindly retry typing.

The latest reported live run launched PID `6424` and found HWND `0x70630` owned by
PID `1476`. Both process records had the same packaged Notepad image path; PID `1476`
reported parent PID `6424` and was created about 156 ms after PID `6424`. This is
strong evidence that the visible Notepad process was spawned by the approved launch,
not an unrelated pre-existing window. The launch PID had exited by the later process
snapshot, so the previous diagnostic correctly left the process-instance link
unconfirmed. The updated guard uses the still-open Popen handle to compare its PID,
image, creation time and exit time with the child's parent PID and creation time;
it accepts only if the original launch process was alive when the child was created.
This run still stopped before editor identification, focus confirmation, or typing;
the earlier focus timeout remains untested.

The same run reported `ResourceWarning` from `subprocess.py:1127` with message
`subprocess 6424 is still running`. This matches CPython's `Popen` finalizer warning
when no return code has yet been recorded. The warning text alone does not prove the
process was still alive—the finalizer checks/polls afterward—and the process was
absent from the later process snapshot. It is a separate process-lifetime issue, not
evidence about focus or input delivery. The integration script continues to expose
the warning rather than suppressing it.

PyAutoGUI's 0.9.54 Windows backend uses `keybd_event` for virtual-key transitions;
Windows' documented `SendInput` is an alternative injection API, but it also targets
the foreground input stream and cannot fix a process-ownership or focus-stage failure.
UIA `ValuePattern.SetValue` would change a control value rather than simulate typing
and could replace content. Neither alternative is adopted without a live diagnostic
showing input delivery is the failing stage.

Windows manual planner acceptance steps are in README. Automated adapter tests do
**not** validate live UIA discovery, actual focus restoration, PyAutoGUI keyboard
behavior, Notepad version compatibility or real Qwen3 action quality. The model-free
script is the required first live check; record Windows and Notepad versions and
actual outcomes separately on a disposable interactive desktop.
