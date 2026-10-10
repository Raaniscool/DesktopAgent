import http.client
import json
from unittest.mock import Mock
import urllib.error
import pytest

from agent import Agent
from config import Config
from ollama_client import ModelError, OllamaClient, _NoRedirect
from safety import Cancellation


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


def test_request_timeout_is_reported_clearly():
    client = client_with_response({})
    client._opener.open.side_effect = TimeoutError("socket timed out")
    with pytest.raises(ModelError, match="may have timed out"):
        client.check_model()


def test_http_error_is_not_misreported_as_connection_failure():
    client = client_with_response({})
    client._opener.open.side_effect = urllib.error.HTTPError(
        "http://127.0.0.1:11434/api/tags", 404, "Not Found", {}, None
    )
    with pytest.raises(ModelError, match="HTTP 404") as error:
        client.check_model()
    assert "Cannot reach" not in str(error.value)


def test_incomplete_http_response_is_reported_as_model_error():
    client = client_with_response({})
    response = client._opener.open.return_value.__enter__.return_value
    response.read.side_effect = http.client.IncompleteRead(b'{"models":', 1)
    with pytest.raises(ModelError, match="incomplete or malformed HTTP response"):
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


def test_agent_never_executes_multiple_native_tool_calls(registry, controller):
    call = {"function": {"name": "open_notepad", "arguments": {}}}
    client = client_with_response({"message": {"content": "", "tool_calls": [call, call]}})
    client.check_model = Mock()
    approve = Mock(return_value=True)

    outcome = Agent(Config(), client, registry, approve, Cancellation()).run("Open Notepad")

    assert outcome.reason == "model_error"
    approve.assert_not_called()
    assert not controller.mock_calls


@pytest.mark.parametrize("function", [
    {"name": "run_shell", "arguments": {"command": "dir"}},
    {"name": "type_text", "arguments": {"text": "safe", "extra": True}},
])
def test_agent_rejects_native_unknown_tools_and_extra_arguments(registry, controller, function):
    client = client_with_response({"message": {"content": "", "tool_calls": [{"function": function}]}})
    client.check_model = Mock()
    approve = Mock(return_value=True)

    outcome = Agent(Config(), client, registry, approve, Cancellation()).run("Do the task")

    assert outcome.reason == "invalid_action"
    approve.assert_not_called()
    assert not controller.mock_calls


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
