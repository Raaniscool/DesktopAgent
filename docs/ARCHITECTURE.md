# Architecture

- `agent.py`: bounded single-action JSON planner loop, action history, duplicate
  guard, CLI and deterministic evidence report. No model-generated code executes.
- `ollama_client.py`: stdlib local HTTP transport, model availability check,
  bounded responses, timeouts and structured text output. No cloud fallback.
- `config.py`: immutable validated configuration separate from execution.
- `tools/registry.py`: exact argument validation and approval gate. Applications
  and keyboard modules declare only the three supported tools.
- `safety.py`: mandatory console approval and cooperative cancellation token.
- `windows_controller.py`: lazy Windows imports, fixed Notepad launch, pywinauto
  UIA identification/focus/readback, PyAutoGUI input with fail-safe enabled.
- `observation.py`: verified/unverified/failed/denied/cancelled results and history.

Flow: task → local model proposal → validate → display/approve → recheck
cancellation → adapter → result history/model feedback → final or bounded stop.
Invalid actions stop immediately. Non-verified executions forbid further tools.
A final model explanation is advisory; evidence comes from deterministic results.

The structure adds dedicated transport, safety, observation and controller modules
instead of putting everything in `agent.py`. There is no empty `mouse.py`:
mouse control is not a milestone-1 tool. No UI or image pipeline is implemented.
Tests use injected fake clients/controllers and mocked adapter dependencies;
importing modules alone cannot control a desktop.
