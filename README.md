# DesktopAgent

A local-first Windows computer-control **CLI prototype**. Python plans with local
Ollama (`qwen3:4b` by default), validates a tiny tool allowlist, asks approval for
**every** action, and records execution evidence. No paid API, GUI, screenshots,
shell tool, file tool, or browser automation is included.

## Status and repository

Milestone 1 is implemented with automated mocked tests. **Real Windows Notepad and
real Ollama/model integration still require the manual acceptance test below.**
Do not treat mocked test results as evidence that your desktop workflow works.
Changes live in the existing canonical repository on `arena/4f30143d-desktopagent`;
they have **not been pushed or integrated into `main`**. Integration requires an
authorized review/merge into canonical `main`; there is no alternate project home.

## Windows setup (PowerShell, Python 3.11+)

First ensure your checkout contains `agent.py` and `requirements.txt`. A clone of
README-only `main` cannot run the prototype: the implementation must first be
published and merged into `main` with authorization. After that integration, run
these commands from `C:\Users\Raani\DesktopAgent` (or your actual clone path):

```powershell
git switch main
git pull --ff-only origin main
Test-Path .\agent.py
Test-Path .\requirements.txt
```

Both checks must return `True`. Do not continue if the project files are missing.
Git commands must run **inside the clone**, not its parent directory.

Check that Python 3.11 is available:

```powershell
py -3.11 --version
```

If your Python launcher says no matching runtime is installed and suggests
`py install 3.11`, run that command, then retry the version check. If your launcher
does not support `py install`, install Python 3.11 from https://www.python.org/downloads/
with the Windows launcher enabled, reopen PowerShell, and retry. A Python install
is a user setup step, not something the agent performs.

Only after the version check succeeds:

```powershell
py -3.11 -m venv .venv
Test-Path .\.venv\Scripts\python.exe
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The virtual-environment check must return `True`. If creating `.venv` fails, stop
and fix that error first; subsequent `.venv` commands will not work. Activation is
not required, and there is no need to change PowerShell's execution policy.

Install Ollama for Windows from https://ollama.com and start it. Then:

```powershell
ollama pull qwen3:4b
ollama list
.\.venv\Scripts\python.exe agent.py --check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe agent.py --task "Open Notepad and type Hello from DesktopAgent."
```

If the service isn't running, start the Ollama app or `ollama serve`. `--check`
checks service/model availability without desktop imports/actions. Model download
is your explicit setup action; the agent never installs anything itself. Use a
current Ollama version supporting structured JSON output and `think: false`.
Qwen3:4B is used for **text-only** reasoning; no image capability is assumed or used.

Type `yes` separately for each proposed action. Anything else cancels approval.
Inspect the proposed text before approving. Ctrl+C cancels; moving the pointer to
a PyAutoGUI fail-safe corner interrupts input. Do not touch keyboard/mouse or
change focus while an approved action is executing. Release modifier keys, turn
Caps Lock off, and select the standard **US English keyboard layout**.

### Windows manual acceptance test (not run in the development sandbox)

1. Use a normal, non-elevated interactive Windows desktop; close **all** Notepad
   windows first. Disable Notepad session restore (start a new session) if needed.
2. Run `--check`; expect the model to be installed and the local service reachable.
3. Run the example command. Expect a proposal for `open_notepad`, then `type_text`.
4. Approve each individually. Confirm a single blank editor opens and the exact
   text `Hello from DesktopAgent.` appears. Expect both records to be `verified`.
5. Repeat with approval declined: no declined action should execute.
6. On a disposable blank document, test Ctrl+C, fail-safe corner interruption,
   focus loss, and an unsupported keyboard layout. Input must stop/refuse; partial
   input can remain. Record Windows/Notepad/Ollama versions and actual outcomes.
7. If the model produces invalid JSON/actions, the agent should stop without
   executing the invalid proposal. If Notepad's UIA editor cannot be identified,
   it should refuse input. Report that limitation rather than disabling guards.

## Scope and limitations

- `open_notepad`: fixed Windows executable; one blank accessible editor required.
  Modern Notepad may restore tabs or have unsupported UIA controls; refusals are
  intentional. Launched windows are not auto-closed on failure/cancellation.
- `type_text`: printable ASCII plus newlines, 1–1000 characters by default. Appends
  to the **identified Notepad editor**, not arbitrary foreground applications.
  This deliberate scope restriction avoids typing into the approval terminal.
- `press_key`: only enter/backspace/arrow keys. Its effect is **unverified**, so the
  agent stops further actions after it. No hotkey/save/submit tools are exposed.
- Typing compares before/after text locally; document contents are not sent back
  to the model. Only status summaries are. No screenshots/clipboard are used.
- Non-verified results halt further execution; the model gets one final-response
  opportunity within the step budget. No automatic retries. Duplicate identical
  actions are refused. Every planner response counts toward the step limit.
- A model's final summary is explicitly labeled as not independent verification.
  Exact typed-text evidence is not proof of general task completion or saved files.
- UIA calls can stall inside Windows despite the bounded launch polling loop;
  focus checks reduce but cannot eliminate races with human/other-process input.
  This is not a security sandbox. Use a disposable, nonsensitive desktop first.

## Configuration

Environment variables (PowerShell examples):

```powershell
$env:DESKTOPAGENT_MODEL = "qwen3:4b"
$env:DESKTOPAGENT_OLLAMA_URL = "http://127.0.0.1:11434"
$env:DESKTOPAGENT_MAX_STEPS = "8"
$env:DESKTOPAGENT_TIMEOUT = "90"
```

Only plain loopback HTTP URLs are accepted; proxies/redirects are disabled.
Timeouts and loop sizes are validated. Approvals cannot be disabled. Other
validated defaults live in `config.py`. Logs go to stderr, include tool names,
statuses and exception classes, and exclude typed text/document contents. Tasks
and proposed text are sent to your local model; never provide secrets. Interactive
task entry (omit `--task`) avoids putting task text in shell history.

See [Architecture](docs/ARCHITECTURE.md), [Safety](docs/SAFETY.md),
[Roadmap](docs/ROADMAP.md), and [Testing](docs/TESTING.md).
