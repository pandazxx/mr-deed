"""Tests for the interface hosts use to embed DefaultAgent: session continuation, the event hook,
cooperative cancellation and host tools."""

import json
import signal
import threading
import time

from mr_deed import Tool
from mr_deed.agents.default import DefaultAgent
from mr_deed.environments.local import LocalEnvironment
from mr_deed.exceptions import FormatError
from mr_deed.models.test_models import DeterministicToolcallModel, make_toolcall_output
from tests.agents.test_default import (  # noqa: F401  (fixtures are registered by importing them)
    default_config,
    get_text,
    model_factory,
    toolcall_config,
)

SUBMIT = "echo 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT'\necho '{}'"
NO_ARGS = {"type": "object", "properties": {}}


class _RecordingToolcallModel(DeterministicToolcallModel):
    """Remembers what it was last queried with."""

    def query(self, messages, **kwargs):
        self.last_query = (list(messages), kwargs)
        return super().query(messages, **kwargs)


class _FormatErrorModel(DeterministicToolcallModel):
    def query(self, messages, **kwargs):
        raise FormatError(
            {"role": "user", "content": "No tool calls found.", "extra": {"interrupt_type": "FormatError"}}
        )


def _tc_model(*steps: tuple[str, str, dict]) -> _RecordingToolcallModel:
    """Toolcall model from (content, tool name, arguments) steps, one tool call per step."""
    outputs = []
    for i, (content, name, args) in enumerate(steps):
        call = {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        outputs.append(make_toolcall_output(content, [call], [{"name": name, **args, "tool_call_id": f"call_{i}"}]))
    return _RecordingToolcallModel(outputs=outputs)


def test_continue_run_keeps_the_conversation_and_resets_per_run_limits(model_factory):
    factory, config = model_factory
    agent = DefaultAgent(
        model=factory(
            [
                ("Step", [{"command": "echo first"}]),
                ("Done", [{"command": SUBMIT.format("done1")}]),
                ("Again", [{"command": SUBMIT.format("done2")}]),
            ]
        ),
        env=LocalEnvironment(),
        **{**config, "continue_template": "Follow-up: {{ task }} ({{ mood }})", "step_limit": 2},
    )
    assert agent.run("first task")["submission"] == "done1\n"
    assert (agent.n_calls, agent.cost) == (2, 2.0)
    n_messages = len(agent.messages)

    # Without the per-run reset the step limit of 2 would already be exhausted here
    assert agent.continue_run("second task", mood="curious")["submission"] == "done2\n"
    assert (agent.n_calls, agent.cost) == (1, 1.0)
    assert (agent.total_n_calls, agent.total_cost) == (3, 3.0)
    assert agent.messages[n_messages - 1]["role"] == "exit"  # the first run's exit record stays in the trajectory
    assert get_text(agent.messages[n_messages]) == "Follow-up: second task (curious)"
    assert agent.serialize()["info"]["model_stats"] == {"instance_cost": 3.0, "api_calls": 3}


def test_model_is_queried_without_exit_records_and_with_the_current_tools(toolcall_config):
    model = _tc_model(
        ("Done", "bash", {"command": SUBMIT.format("one")}), ("Done", "bash", {"command": SUBMIT.format("two")})
    )
    tool = Tool("noop", "Does nothing", NO_ARGS, lambda args: {"output": ""})
    agent = DefaultAgent(model=model, env=LocalEnvironment(), **toolcall_config)
    agent.run("one")
    agent.tools = [tool]
    agent.continue_run("two")

    messages, kwargs = model.last_query
    # The submission got a tool result, so the continued conversation has no dangling tool call
    assert [m.get("role") for m in messages] == ["system", "user", "assistant", "tool", "user"]
    assert kwargs == {"tools": [tool]}


def test_from_trajectory_restores_the_conversation(tmp_path, toolcall_config):
    path = tmp_path / "run.traj.json"
    first = DefaultAgent(
        _tc_model(("Done", "bash", {"command": SUBMIT.format("one")})),
        LocalEnvironment(),
        **{**toolcall_config, "output_path": path, "step_limit": 7},
    )
    first.run("one")

    agent = DefaultAgent.from_trajectory(
        path, _tc_model(("Done", "bash", {"command": SUBMIT.format("two")})), LocalEnvironment(), output_path=None
    )
    assert agent.messages == first.messages
    assert (agent.config.step_limit, agent.config.output_path) == (7, None)
    assert (agent.total_n_calls, agent.total_cost) == (1, 1.0)
    assert agent.continue_run("two")["submission"] == "two\n"
    assert (agent.total_n_calls, agent.n_calls) == (2, 1)
    assert len(agent.messages) == len(first.messages) + 4  # user, assistant, observation, exit


def test_on_event_mirrors_the_trajectory(model_factory):
    factory, config = model_factory
    events = []
    agent = DefaultAgent(
        model=factory([("Step", [{"command": "echo hi"}]), ("Done", [{"command": SUBMIT.format("ok")}])]),
        env=LocalEnvironment(),
        on_event=lambda kind, payload: events.append((kind, payload)),
        **config,
    )
    agent.run("task")

    kinds = ["system", "user", "assistant", "action", "observation", "assistant", "action", "observation", "exit"]
    assert [kind for kind, _ in events] == kinds
    message_payloads = [payload for kind, payload in events if kind != "action"]
    assert all(payload is message for payload, message in zip(message_payloads, agent.messages, strict=True))
    assert events[3][1] == agent.messages[2]["extra"]["actions"][0]
    assert events[-1][1]["extra"]["exit_status"] == "Submitted"


def test_format_error_and_limit_events(toolcall_config):
    kinds = []
    agent = DefaultAgent(
        _FormatErrorModel(outputs=[]),
        LocalEnvironment(),
        on_event=lambda kind, payload: kinds.append(kind),
        **{**toolcall_config, "max_consecutive_format_errors": 2},
    )
    assert agent.run("task")["exit_status"] == "RepeatedFormatError"
    assert kinds == ["system", "user", "format_error", "format_error", "exit"]

    exits = []
    agent = DefaultAgent(
        _tc_model(("A", "bash", {"command": "echo a"}), ("B", "bash", {"command": "echo b"})),
        LocalEnvironment(),
        on_event=lambda kind, payload: kind == "exit" and exits.append(payload["extra"]["exit_status"]),
        **{**toolcall_config, "step_limit": 1},
    )
    assert agent.run("task")["exit_status"] == "LimitsExceeded"
    assert exits == ["LimitsExceeded"]


def test_host_tools_are_routed_by_name_and_observed(toolcall_config):
    calls = []

    def add(args: dict) -> dict:
        calls.append(args)
        return {"output": str(args["a"] + args["b"])}

    parameters = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
    events = []
    agent = DefaultAgent(
        _tc_model(("Adding", "add", {"a": 1, "b": 2}), ("Done", "bash", {"command": SUBMIT.format("3")})),
        LocalEnvironment(),
        tools=[Tool("add", "Add two numbers", parameters, add)],
        on_event=lambda kind, payload: events.append((kind, payload)),
        **toolcall_config,
    )
    assert agent.run("add 1 and 2")["submission"] == "3\n"
    assert calls == [{"a": 1, "b": 2}]  # the handler sees the arguments only
    observation = agent.messages[3]
    assert (observation["role"], observation["tool_call_id"], observation["extra"]["returncode"]) == (
        "tool",
        "call_0",
        0,
    )
    assert "<output>\n3</output>" in observation["content"]
    assert ("action", {"name": "add", "a": 1, "b": 2, "tool_call_id": "call_0"}) in events


def test_cancel_event_stops_before_the_first_query(toolcall_config, tmp_path):
    path = tmp_path / "cancelled.traj.json"
    cancel = threading.Event()
    agent = DefaultAgent(
        _tc_model(("A", "bash", {"command": "echo a"})),
        LocalEnvironment(),
        cancel_event=cancel,
        **{**toolcall_config, "output_path": path},
    )
    cancel.set()
    assert agent.run("task")["exit_status"] == "Cancelled"
    assert (agent.n_calls, [m["role"] for m in agent.messages]) == (0, ["system", "user", "exit"])
    assert json.loads(path.read_text())["info"]["exit_status"] == "Cancelled"


def test_cancel_during_an_action_skips_the_remaining_actions(toolcall_config):
    def trip(args: dict) -> dict:
        agent.cancel()
        return {"output": "tripped"}

    calls = [
        {"id": "c0", "type": "function", "function": {"name": "trip", "arguments": "{}"}},
        {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "echo never"}'}},
    ]
    actions = [{"name": "trip", "tool_call_id": "c0"}, {"name": "bash", "command": "echo never", "tool_call_id": "c1"}]
    agent = DefaultAgent(
        DeterministicToolcallModel(outputs=[make_toolcall_output("Two actions", calls, actions)]),
        LocalEnvironment(),
        tools=[Tool("trip", "Cancels the run", NO_ARGS, trip)],
        **toolcall_config,
    )
    assert agent.run("task")["exit_status"] == "Cancelled"
    observations = [m for m in agent.messages if m.get("role") == "tool"]
    assert "tripped" in observations[0]["content"]
    assert "action was not executed" in observations[1]["content"]


def test_cancel_from_another_thread_kills_the_running_command(toolcall_config):
    started, results = threading.Event(), []
    agent = DefaultAgent(
        _tc_model(("Sleep", "bash", {"command": "sleep 30"}), ("Never", "bash", {"command": "echo never"})),
        LocalEnvironment(timeout=60),
        on_event=lambda kind, payload: kind == "action" and started.set(),
        **toolcall_config,
    )
    thread = threading.Thread(target=lambda: results.append(agent.run("task")))
    thread.start()
    assert started.wait(5)
    deadline = time.time() + 10
    while thread.is_alive() and time.time() < deadline:
        agent.cancel()  # idempotent: repeat until the command has actually been spawned and killed
        thread.join(0.1)

    assert not thread.is_alive()
    assert results[0]["exit_status"] == "Cancelled"
    assert agent.messages[3]["extra"]["returncode"] == -signal.SIGKILL  # killed, not timed out
    assert agent.n_calls == 1
