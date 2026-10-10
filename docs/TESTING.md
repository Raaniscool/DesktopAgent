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
child** of the Popen process; the Popen handle's PID and creation time must match the
launch-time sample; its image path must match the window's; and the parent must have
been alive when the child was created. If the later `QueryFullProcessImageNameW` call
cannot read the exited process's image path, the launch-time path is used only after
the handle PID and creation-time match succeeds. Missing or contradictory evidence
fails closed before editor traversal. The accepted window must still contain one blank
accessible editor, and typing still requires separate approval. Document contents,
window titles and exception messages are not logged.
`ResourceWarning` messages include source location; the unique test string is
redacted from warning text. Executable paths may include local account/profile names.
Inspect the open document before closing it. If the test fails, retain its stage logs
and do not blindly retry typing.

The latest live run launched PID `4252` (created `2026-10-10T22:41:54.873113Z`) and
found a Notepad window owned by PID `2756`, whose parent PID was `4252`. The child
was created at `2026-10-10T22:41:55.023259Z`, about 150.146 ms after launch and
181.320 ms before the launch process exited at `2026-10-10T22:41:55.204579Z`. Both
process records reported the same packaged Notepad image path:
`C:\Program Files\WindowsApps\Microsoft.WindowsNotepad_11.2607.14.0_x64__8wekyb3d8bbwe\Notepad\Notepad.exe`.
The ownership check still stopped safely before editor traversal, focus confirmation,
or typing because `QueryFullProcessImageNameW` on the exited Popen handle returned
Win32 error 31, leaving `same_executable_image` incomplete despite the launch-time
image path and matching Popen PID/creation-time evidence. The local guard now keeps
that launch-time handle identity and permits its image path as a fallback only if its
PID and creation time match the same handle at mismatch; the direct-parent, image,
creation-order, and process-lifetime checks remain. Mocked tests pass, but no post-change
live Windows run has been made; this does not yet confirm the ownership change or any
focus/input behavior.

The same run reported `ResourceWarning` from `subprocess.py:1127` with message
`subprocess 4252 is still running`. The captured exit time shows PID `4252` exited at
`2026-10-10T22:41:55.204579Z`; the warning alone does not establish that it was still
running. It is a separate process-lifetime issue, not evidence about focus or input
delivery. The integration script continues to expose the warning rather than suppressing
it.

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
