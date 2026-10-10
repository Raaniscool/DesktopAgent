# Testing

Run `python -m pytest -q` from the repository root. Automated tests never call
real desktop APIs or require Ollama. Fixtures inject mocked controllers/clients;
adapter tests replace focus, keyboard and readback dependencies. Transport tests
replace the HTTP opener, including unavailable-service and malformed responses.

Coverage includes unknown tools, strict arguments, unsupported text/keys,
mandatory approval, cancellation including Ctrl+C at approval, repeated actions,
bounded steps, accurate failure/unverified reporting, native tool-call request/
response parsing, rejection of malformed or multiple calls, connection/timeout/
HTTP-status/truncated-response handling, local-only configuration, missing-model
guidance, exact append verification and a mocked Notepad workflow. INFO logs record
each planner response's wall-clock latency/type and tool name/status without
task text or tool arguments; these timings become meaningful model measurements
only when run against the actual local Ollama service.

Windows manual acceptance steps are in README. Automated adapter tests do **not**
validate UIA discovery, actual focus restoration, PyAutoGUI keyboard behavior,
Notepad version compatibility or real Qwen3 action quality. Record these results
separately on a disposable interactive Windows desktop before normal use.
