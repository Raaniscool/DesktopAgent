"""Strict deterministic validation, followed by mandatory approval."""
from dataclasses import dataclass
import logging
from typing import Callable

from observation import ToolResult
from safety import Cancellation

logger = logging.getLogger(__name__)
PERMITTED_KEYS = ("enter", "backspace", "left", "right", "up", "down")


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict
    required: tuple[str, ...]
    execute: Callable[..., ToolResult]

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": self.properties,
                               "required": list(self.required), "additionalProperties": False}}


class ToolRegistry:
    def __init__(self, tools: list[Tool], max_text_length: int = 1000) -> None:
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool definitions")
        self.max_text_length = max_text_length

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self.tools.values()]

    def validate(self, name: str, arguments: dict) -> Tool:
        if not isinstance(name, str) or name not in self.tools:
            raise ValidationError("Unknown tool; use only the advertised tools")
        tool = self.tools[name]
        if type(arguments) is not dict:
            raise ValidationError("Tool arguments must be an object")
        if set(arguments) != set(tool.required):
            raise ValidationError("Arguments must exactly match the required schema fields")
        if name == "type_text":
            text = arguments["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= self.max_text_length:
                raise ValidationError(f"text must contain 1–{self.max_text_length} characters")
            if any(char != "\n" and not 32 <= ord(char) <= 126 for char in text):
                raise ValidationError("Only printable ASCII and newline are supported; no tabs or control characters")
        if name == "press_key" and arguments["key"] not in PERMITTED_KEYS:
            raise ValidationError("key must be one of: " + ", ".join(PERMITTED_KEYS))
        # For future registered tools, validate primitive types and enums too.
        for field, schema in tool.properties.items():
            value = arguments[field]
            if schema.get("type") == "string" and not isinstance(value, str):
                raise ValidationError(f"{field} must be a string")
            if "enum" in schema and value not in schema["enum"]:
                raise ValidationError(f"{field} is not permitted")
        return tool

    def execute(self, name: str, arguments: dict, approve: Callable[[str, dict], bool],
                cancellation: Cancellation) -> ToolResult:
        tool = self.validate(name, arguments)
        if cancellation.cancelled:
            return ToolResult("cancelled", "Task cancelled before approval; no input sent")
        # Do not hand the approver the mutable arguments used for execution.
        try:
            approved = approve(name, dict(arguments))
        except (EOFError, KeyboardInterrupt):
            approved = False
        if approved is not True:
            return ToolResult("denied", "Approval declined; no action executed")
        if cancellation.cancelled:
            return ToolResult("cancelled", "Task cancelled after approval; no action executed")
        try:
            result = tool.execute(**arguments)
            if not isinstance(result, ToolResult):
                raise TypeError("Tool returned an invalid result")
            logger.info("tool=%s status=%s", name, result.status)
            return result
        except KeyboardInterrupt:
            cancellation.cancel()
            return ToolResult("cancelled", "Interrupted; action may be partially completed. Inspect Notepad")
        except Exception as exc:
            # Exception text can contain document content: log class, not payload/traceback.
            logger.warning("tool=%s error_type=%s", name, type(exc).__name__)
            return ToolResult("failed", "Action failed (" + type(exc).__name__ +
                              "); input may be partial. Inspect Notepad before trying again")
