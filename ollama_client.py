"""Bounded stdlib HTTP client for a local Ollama service (no cloud fallback)."""
import json
import urllib.error
import urllib.request

from config import Config

MAX_RESPONSE_BYTES = 1_000_000


class ModelError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Ollama redirects are refused; configure the local service URL directly")


class OllamaClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        # Never send loopback requests through environment proxy servers.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.config.ollama_url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=self.config.request_timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ModelError("Ollama response exceeded the size limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ModelError("Ollama returned a non-object response")
            if "error" in result:
                raise ModelError("Ollama reported an error; check 'ollama ps' and the service logs")
            return result
        except ModelError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError("Cannot reach local Ollama. Install/start Ollama, run 'ollama serve' "
                             "if needed, and check DESKTOPAGENT_OLLAMA_URL. The request may have timed out") from None
        except (ValueError, UnicodeError):
            raise ModelError("Ollama returned malformed JSON") from None

    def check_model(self) -> None:
        tags = self._request("/api/tags")
        models = tags.get("models")
        if not isinstance(models, list) or any(not isinstance(item, dict) for item in models):
            raise ModelError("Ollama /api/tags returned an invalid model list")
        names = {item.get("name") for item in models if isinstance(item.get("name"), str)}
        wanted = self.config.model
        if wanted not in names and (":" in wanted or wanted + ":latest" not in names):
            raise ModelError(f"Model {wanted!r} is not installed. Pull the configured model with "
                             f"'ollama pull {wanted}' and retry")

    def next_action(self, messages: list[dict], schema: dict) -> dict:
        result = self._request("/api/chat", {
            "model": self.config.model, "messages": messages, "stream": False,
            "think": False, "format": schema,
            "options": {"temperature": 0, "num_predict": 1024},
        })
        message = result.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelError("Ollama response has no assistant content")
        try:
            action = json.loads(message["content"])
        except (ValueError, TypeError):
            raise ModelError("Model did not return a valid JSON action; no action executed") from None
        if not isinstance(action, dict):
            raise ModelError("Model action must be an object")
        return action
