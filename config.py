"""Validated, local-only configuration. Approvals cannot be disabled."""
from dataclasses import dataclass
import os
from urllib.parse import urlparse


DEFAULT_MODEL = "qwen3:1.7b"


@dataclass(frozen=True)
class Config:
    model: str = DEFAULT_MODEL
    ollama_url: str = "http://127.0.0.1:11434"
    max_steps: int = 8
    request_timeout: float = 90.0
    launch_timeout: float = 10.0
    max_text_length: int = 1000

    def __post_init__(self) -> None:
        url = urlparse(self.ollama_url)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.path not in {"", "/"}
                or url.query or url.fragment):
            raise ValueError("Ollama URL must be a plain HTTP loopback address, e.g. http://127.0.0.1:11434")
        # Accessing port also validates malformed port strings.
        _ = url.port
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Model name must not be empty")
        for name, value, maximum in [("max_steps", self.max_steps, 50),
                                     ("max_text_length", self.max_text_length, 5000)]:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer between 1 and {maximum}")
        for value in (self.request_timeout, self.launch_timeout):
            if type(value) not in {int, float} or not 0 < value <= 300:
                raise ValueError("Timeouts must be greater than zero and at most 300 seconds")

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            model=os.getenv("DESKTOPAGENT_MODEL", DEFAULT_MODEL),
            ollama_url=os.getenv("DESKTOPAGENT_OLLAMA_URL", "http://127.0.0.1:11434"),
            max_steps=int(os.getenv("DESKTOPAGENT_MAX_STEPS", "8")),
            request_timeout=float(os.getenv("DESKTOPAGENT_TIMEOUT", "90")),
        )
