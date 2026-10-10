# Safety model

Every computer-control call requires fresh explicit approval. There is no
unattended mode. Only a fixed Notepad launch, bounded ASCII/newline typing and six
keys exist. Model proposals are data, not executable code. No arbitrary shell,
Python, paths, browser, clipboard, screenshots, account operations or downloads.

Notepad must start blank with a single recognized editor, and no existing Notepad
window may be present. Before typing, the controller restores its identified
editor focus and checks foreground window, UIA runtime identity, keyboard layout,
Caps Lock and held modifiers. Typing appends at the end instead of replacing a
selection. Checks repeat per character; PyAutoGUI FAILSAFE stays enabled. An
internal fixed Ctrl+End positions the caret; it is not a model-selectable shortcut.

Checks are risk reductions, not atomic OS guarantees: another process/user can
change focus between a check and input. Notepad versions and remote desktops may
behave differently. Never use this prototype on secrets, elevated applications,
or an unattended desktop. It cannot bypass UAC or permission prompts.

Limits: at most 8 planner turns by default (maximum 50), bounded generated output,
local request timeout, launch polling timeout and text length cap. Computer actions
are never automatically retried. A response containing multiple tools is discarded
without executing any call, then gets at most one corrective model turn; repeated
multi-call output stops. Duplicate actions are refused. Windows UIA calls may block
outside the polling deadline; process-isolated timeouts are future work. Ctrl+C interrupts
normal work; a cancellation token is checked before/after approval and during
input. Cancellation does not roll back partial text or close a launched window.
The PyAutoGUI corner fail-safe may also leave partial input.

Denial, failure, cancellation and unverified execution prohibit further tools.
Tool results sent to the model contain only status summaries, not document text.
Treat future website/document/vision observations as untrusted data. Do not log or
send credentials. Local Ollama still receives the task and proposed arguments;
its own retention/logging policies are outside this application's control.
