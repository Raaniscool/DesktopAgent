# Architecture

- `agent.py`: bounded one-native-tool-call-per-turn planner loop, action history,
  duplicate guard, CLI and deterministic evidence report. No model-generated code executes.
- `ollama_client.py`: stdlib local HTTP transport, model availability check,
  bounded responses, timeouts, and native Ollama function-tool calls. No cloud fallback.
- `config.py`: immutable validated configuration separate from execution.
- `tools/registry.py`: exact argument validation and approval gate. Applications
  and keyboard modules declare only the three supported tools.
- `safety.py`: mandatory console approval and cooperative cancellation token.
- `windows_controller.py`: lazy Windows imports, fixed Notepad launch, pywinauto
  UIA identification/focus/readback, fail-safe PyAutoGUI input and sanitized
  stage-specific typing failures.
- `observation.py`: verified/unverified/failed/denied/cancelled results and history.

Flow: task → native Ollama tool call → validate → display/approve → recheck
cancellation → adapter → role=`tool` result feedback → final or bounded stop. At
most one tool call is executed per response. A multi-call response is discarded
without executing any of its calls; one corrective model turn is allowed, while
malformed or repeated multi-call responses stop safely. Non-verified results
forbid further tools. Final model text is advisory; evidence is deterministic.

Planner logs record each model round trip's wall-clock milliseconds and response
type. Tool logs record the allowlisted tool name and status, never its arguments.

The structure adds dedicated transport, safety, observation and controller modules
instead of putting everything in `agent.py`. There is no empty `mouse.py`:
mouse control is not a milestone-1 tool. No UI or image pipeline is implemented.
Tests use injected fake clients/controllers and mocked adapter dependencies;
importing modules alone cannot control a desktop.
