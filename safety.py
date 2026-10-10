"""Mandatory human approval and cooperative cancellation."""
import json
from threading import Event
from typing import Callable


class Cancellation:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class ConsoleApproval:
    def __init__(self, read: Callable[[str], str] = input,
                 write: Callable[[str], None] = print) -> None:
        self.read = read
        self.write = write

    def __call__(self, name: str, arguments: dict) -> bool:
        # JSON escapes control characters so model output cannot alter the terminal.
        self.write("\nProposed computer-control action: " + json.dumps(
            {"tool": name, "arguments": arguments}, ensure_ascii=True))
        self.write("Target: agent-owned Notepad. Opening may restore Notepad's existing tabs; "
                   "typing appends at the end of the identified editor. No saving is performed.")
        try:
            return self.read("Approve this one action? Type yes; anything else cancels: ").strip().lower() == "yes"
        except (EOFError, KeyboardInterrupt):
            return False
