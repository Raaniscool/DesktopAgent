import json
from unittest.mock import Mock
import urllib.error
import pytest

from config import Config
from ollama_client import ModelError, OllamaClient, _NoRedirect


def client_with_response(payload):
    client = OllamaClient(Config())
    response = Mock()
    response.read.return_value = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    client._opener = Mock()
    client._opener.open.return_value = context
    return client


def test_default_model_is_qwen3_1_7b(monkeypatch):
    monkeypatch.delenv("DESKTOPAGENT_MODEL", raising=False)
    assert Config().model == "qwen3:1.7b"
    assert Config.from_env().model == "qwen3:1.7b"


def test_missing_model_guidance():
    client = client_with_response({"models": [{"name": "other:latest"}]})
    with pytest.raises(ModelError, match="ollama pull qwen3:1.7b"):
        client.check_model()


def test_available_model():
    client_with_response({"models": [{"name": "qwen3:1.7b"}]}).check_model()


def test_service_unavailable():
    client = client_with_response({})
    client._opener.open.side_effect = urllib.error.URLError("refused")
    with pytest.raises(ModelError, match="ollama serve"):
        client.check_model()


@pytest.mark.parametrize("payload", [b"not json", [], {"models": "invalid"}, {"models": [2]}, {"error": "secret"}])
def test_malformed_service_responses(payload):
    with pytest.raises(ModelError):
        client_with_response(payload).check_model()


def test_oversized_response():
    with pytest.raises(ModelError, match="size limit"):
        client_with_response(b"x" * 1_000_001).check_model()


def test_native_tool_call_request_and_response():
    tools = [{"name": "open_notepad", "description": "Open Notepad", "parameters": {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False,
    }}]
    payload = {"message": {"role": "assistant", "content": "", "tool_calls": [{
        "function": {"name": "open_notepad", "arguments": {}}
    }]}}
    client = client_with_response(payload)

    assert client.next_action([], tools) == {"kind": "tool", "tool": "open_notepad", "arguments": {}}
    request = client._opener.open.call_args.args[0]
    data = json.loads(request.data)
    assert data["model"] == "qwen3:1.7b"
    assert data["tools"] == [{"type": "function", "function": tools[0]}]
    assert data["stream"] is False and data["think"] is False
    assert "format" not in data
    assert data["options"]["num_predict"] == 1024


def test_plain_assistant_content_is_final_response():
    client = client_with_response({"message": {"role": "assistant", "content": "Notepad is ready."}})
    assert client.next_action([], []) == {"kind": "final", "message": "Notepad is ready."}


@pytest.mark.parametrize("payload", [
    {},
    {"message": []},
    {"message": {"content": []}},
    {"message": {"content": ""}},
    {"message": {"content": "", "tool_calls": "invalid"}},
    {"message": {"content": "", "tool_calls": [None]}},
    {"message": {"content": "", "tool_calls": [{"function": {
        "name": "type_text", "arguments": []
    }}]}},
])
def test_malformed_chat_responses(payload):
    with pytest.raises(ModelError):
        client_with_response(payload).next_action([], [])


def test_multiple_tool_calls_are_rejected_before_execution():
    call = {"function": {"name": "open_notepad", "arguments": {}}}
    client = client_with_response({"message": {"content": "", "tool_calls": [call, call]}})
    with pytest.raises(ModelError, match="multiple tools"):
        client.next_action([], [])


def test_redirects_refused():
    with pytest.raises(ModelError, match="redirects"):
        _NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")


@pytest.mark.parametrize("url", ["https://localhost:11434", "http://example.com", "http://127.0.0.1@evil.com",
                                    "http://localhost/path", "http://localhost?x=y", "http://localhost:abc"])
def test_remote_or_malformed_endpoints_rejected(url):
    with pytest.raises(ValueError):
        Config(ollama_url=url)


@pytest.mark.parametrize("kwargs", [{"max_steps": True}, {"max_steps": 0}, {"max_steps": 51},
                                      {"request_timeout": float("nan")}, {"request_timeout": 0},
                                      {"model": " "}, {"max_text_length": 6000}])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)
