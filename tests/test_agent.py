from unittest.mock import Mock
import pytest

from agent import Agent
from config import Config
from observation import ToolResult
from ollama_client import ModelError, MultipleToolCallsError
from safety import Cancellation, ConsoleApproval


def tool(name, **arguments):
    return {"kind": "tool", "tool": name, "arguments": arguments}


def finish(message="Done"):
    return {"kind": "final", "message": message}


def make_agent(registry, actions, max_steps=8, approve=True):
    client = Mock()
    client.next_action.side_effect = actions
    agent = Agent(Config(max_steps=max_steps), client, registry, lambda *_: approve, Cancellation())
    return agent, client


def test_notepad_workflow_mocked(registry, controller):
    agent, client = make_agent(registry, [tool("open_notepad"),
                                         tool("type_text", text="Hello from DesktopAgent."), finish()])
    outcome = agent.run("Open Notepad and type Hello from DesktopAgent.")
    assert outcome.reason == "model_finished"
    assert [record.result.status for record in outcome.history] == ["verified", "verified"]
    controller.open_notepad.assert_called_once_with()
    controller.type_text.assert_called_once_with(text="Hello from DesktopAgent.")
    messages = client.next_action.call_args.args[0]
    assert "copy the complete requested text verbatim" in messages[0]["content"]
    assert any(message.get("role") == "assistant" and message.get("tool_calls") for message in messages)
    assert any(message.get("role") == "tool" and '"status": "verified"' in message["content"]
               for message in messages)
    assert "not independent verification" in outcome.render()


def test_model_timing_logs_exclude_task_and_tool_arguments(registry, caplog):
    sensitive = "private typed marker"
    agent, _ = make_agent(registry, [tool("type_text", text=sensitive), finish()])
    caplog.set_level("INFO")

    outcome = agent.run("type " + sensitive)

    assert outcome.reason == "model_finished"
    assert "planner_step=1 response=tool_call elapsed_ms=" in caplog.text
    assert "planner_step=2 response=final elapsed_ms=" in caplog.text
    assert "tool=type_text status=verified" in caplog.text
    assert sensitive not in caplog.text


def test_step_limit(registry, controller):
    agent, client = make_agent(registry, [tool("open_notepad"), tool("type_text", text="stop")], max_steps=1)
    outcome = agent.run("Do a task")
    assert outcome.reason == "step_limit"
    assert client.next_action.call_count == 1
    controller.type_text.assert_not_called()


def test_repeat_guard(registry, controller):
    agent, _ = make_agent(registry, [tool("type_text", text="x"), tool("type_text", text="x")])
    assert agent.run("repeat").reason == "repeated_action"
    controller.type_text.assert_called_once()


def test_multiple_tool_response_is_discarded_and_replanned_once(registry, controller):
    client = Mock()
    client.next_action.side_effect = [
        MultipleToolCallsError("Model requested multiple tools at once"),
        tool("open_notepad"),
        finish(),
    ]
    approve = Mock(return_value=True)
    agent = Agent(Config(), client, registry, approve, Cancellation())

    outcome = agent.run("Open Notepad")

    assert outcome.reason == "model_finished"
    assert client.next_action.call_count == 3
    retry_messages = client.next_action.call_args_list[1].args[0]
    assert any(message.get("role") == "user" and
               "No action from that response was executed" in message.get("content", "")
               for message in retry_messages)
    approve.assert_called_once()
    controller.open_notepad.assert_called_once()


def test_repeated_multiple_tool_responses_stop_safely(registry, controller):
    client = Mock()
    client.next_action.side_effect = [
        MultipleToolCallsError("multiple"), MultipleToolCallsError("multiple"), tool("open_notepad")
    ]
    approve = Mock(return_value=True)
    outcome = Agent(Config(), client, registry, approve, Cancellation()).run("Open Notepad")

    assert outcome.reason == "model_error"
    assert "repeatedly requested multiple tools" in outcome.message
    assert client.next_action.call_count == 2
    approve.assert_not_called()
    assert not controller.mock_calls


def test_multiple_tool_response_respects_step_limit(registry, controller):
    client = Mock()
    client.next_action.side_effect = [MultipleToolCallsError("multiple"), tool("open_notepad")]
    approve = Mock(return_value=True)
    outcome = Agent(Config(max_steps=1), client, registry, approve, Cancellation()).run("Open Notepad")

    assert outcome.reason == "step_limit"
    assert client.next_action.call_count == 1
    approve.assert_not_called()
    assert not controller.mock_calls


@pytest.mark.parametrize("status", ["failed", "unverified", "cancelled"])
def test_nonverified_actions_block_further_execution(registry, controller, status):
    controller.open_notepad.return_value = ToolResult(status, "Not complete")
    agent, _ = make_agent(registry, [tool("open_notepad"), tool("type_text", text="bad")])
    outcome = agent.run("task")
    assert outcome.reason == status
    assert outcome.history[0].result.status == status
    controller.type_text.assert_not_called()


def test_denial_gets_model_explanation_no_second_action(registry, controller):
    agent, client = make_agent(registry, [tool("open_notepad"), finish("You declined")], approve=False)
    outcome = agent.run("task")
    assert outcome.reason == "denied"
    assert outcome.message == "You declined"
    assert '"status": "denied"' in str(client.next_action.call_args)
    controller.open_notepad.assert_not_called()


@pytest.mark.parametrize("action", [[], {}, {"kind": "tool", "tool": "exec", "arguments": {}},
    {"kind": "final", "message": 12}, {"kind": "final", "message": "x", "extra": 1},
    {"kind": "tool", "tool": "open_notepad", "arguments": {}, "message": "do it"}])
def test_invalid_model_actions(registry, controller, action):
    agent, _ = make_agent(registry, [action])
    assert agent.run("task").reason == "invalid_action"
    assert not controller.mock_calls


def test_model_failure_does_not_erase_history(registry, controller):
    agent, _ = make_agent(registry, [tool("open_notepad"), ModelError("Local model error")])
    outcome = agent.run("task")
    assert outcome.reason == "model_error"
    assert len(outcome.history) == 1


def test_missing_model_or_service(registry, controller):
    agent, client = make_agent(registry, [])
    client.check_model.side_effect = ModelError("Start ollama serve")
    assert agent.run("task").reason == "model_error"
    client.next_action.assert_not_called()
    assert not controller.mock_calls


def test_cancelled_proposal_is_discarded(registry, controller):
    agent, client = make_agent(registry, [])
    def propose(*_):
        agent.cancellation.cancel()
        return tool("open_notepad")
    client.next_action.side_effect = propose
    assert agent.run("task").reason == "cancelled"
    assert not controller.mock_calls


def test_ctrl_c_during_approval_cancels_without_replanning(registry, controller):
    def interrupt(_):
        raise KeyboardInterrupt

    client = Mock()
    client.next_action.return_value = tool("open_notepad")
    cancellation = Cancellation()
    approval = ConsoleApproval(read=interrupt, write=lambda _: None)
    agent = Agent(Config(), client, registry, approval, cancellation)

    outcome = agent.run("Open Notepad")

    assert outcome.reason == "cancelled"
    assert cancellation.cancelled
    client.next_action.assert_called_once()
    controller.open_notepad.assert_not_called()


@pytest.mark.parametrize("task", ["", " ", "x" * 4001, None])
def test_invalid_task_does_not_call_model(registry, task):
    agent, client = make_agent(registry, [])
    assert agent.run(task).reason == "invalid_task"
    client.check_model.assert_not_called()
