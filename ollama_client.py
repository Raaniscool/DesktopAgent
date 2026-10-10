"""Bounded stdlib HTTP client for a local Ollama service (no cloud fallback)."""
import http.client
import json
import urllib.error
import urllib.request

from config import Config

MAX_RESPONSE_BYTES = 1_000_000


class ModelError(RuntimeError):
    pass


class MultipleToolCallsError(ModelError):
    """Recoverable protocol error: no call from the response was executed."""


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
        except urllib.error.HTTPError as exc:
            raise ModelError(f"Local Ollama responded with HTTP {exc.code}; verify the service URL, "
                             "configured model, and support for native tool calls") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError("Cannot reach local Ollama. Install/start Ollama, run 'ollama serve' "
                             "if needed, and check DESKTOPAGENT_OLLAMA_URL. The request may have timed out") from None
        except http.client.HTTPException:
            raise ModelError("Ollama returned an incomplete or malformed HTTP response") from None
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

    def next_action(self, messages: list[dict], tools: list[dict]) -> dict:
        """Request one native Ollama function call or a plain-text final response."""
        native_tools = [{"type": "function", "function": tool} for tool in tools]
        result = self._request("/api/chat", {
            "model": self.config.model, "messages": messages, "stream": False,
            "think": False, "tools": native_tools,
            "options": {"temperature": 0, "num_predict": 1024},
        })
        message = result.get("message")
        if not isinstance(message, dict):
            raise ModelError("Ollama response has no assistant message")

        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise ModelError("Ollama returned malformed tool calls; no action executed")
        if len(tool_calls) > 1:
            raise MultipleToolCallsError("Model requested multiple tools at once; no calls from this response executed")
        if tool_calls:
            call = tool_calls[0]
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(function.get("name"), str)
                    or type(function.get("arguments")) is not dict):
                raise ModelError("Ollama returned a malformed function call; no action executed")
            return {"kind": "tool", "tool": function["name"], "arguments": function["arguments"]}

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelError("Ollama returned neither a tool call nor a final response")
        return {"kind": "final", "message": content}
