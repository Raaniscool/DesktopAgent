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
counts. If launch and window PIDs differ, the test also reports read-only executable
identity, creation time and bounded parent-chain snapshots for both PIDs. These
snapshots are troubleshooting evidence only: they do not establish ownership or
permit input, and the controller still refuses the PID mismatch before editor
traversal, focus, or keyboard actions. Document contents, window titles and exception
messages are not logged. A `ResourceWarning` includes its message and source location
so its cause can be distinguished; the unique test string is redacted from warning
messages. Inspect the open document before closing it. If the test fails, retain its
stage logs and do not blindly retry typing.

The latest reported live run stopped at window ownership: the launch returned PID
`360`, while the discovered visible window reported PID `18700`. It failed closed
before editor identification, focus confirmation, or keyboard input. This run does
not resolve the earlier focus timeout. The new process snapshots are intended to
show whether the mismatched processes share a verified parent/ancestor relationship
and which executable images they represent; even a plausible Windows activation
handoff does not waive the exact-PID ownership check. The `ResourceWarning` category
was reported but its message was not captured in that run. A likely independent
source is CPython's `Popen` finalizer warning when no return code has yet been
recorded for the launched GUI process. The next diagnostic run exposes the exact
message/source to verify or rule this out. That warning alone does not prove the
process was still running (the finalizer checks its state afterward), and it is not
evidence about focus or input delivery.

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
