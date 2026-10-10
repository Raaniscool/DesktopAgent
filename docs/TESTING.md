# Testing

Run `python -m pytest -q` from the repository root. Automated tests never call
real desktop APIs or require Ollama. Fixtures inject mocked controllers/clients;
adapter tests replace focus, keyboard and readback dependencies. Transport tests
replace the HTTP opener, including unavailable-service and malformed responses.

Coverage includes unknown tools, strict arguments, unsupported text/keys,
mandatory approval, cancellation, repeated actions, bounded steps, accurate
failure/unverified reporting, model errors, local-only configuration, missing
model/service guidance, exact append verification and mocked Notepad workflow.

Windows manual acceptance steps are in README. Automated adapter tests do **not**
validate UIA discovery, actual focus restoration, PyAutoGUI keyboard behavior,
Notepad version compatibility or real Qwen3 action quality. Record these results
separately on a disposable interactive Windows desktop before normal use.
