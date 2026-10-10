"""Execution evidence, intentionally excluding desktop contents and typed text."""
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolResult:
    status: Literal["verified", "unverified", "failed", "denied", "cancelled"]
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ActionRecord:
    tool: str
    result: ToolResult
