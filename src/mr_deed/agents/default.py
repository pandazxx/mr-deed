"""Basic agent class. See https://pandazxx.github.io/mr-deed/latest/advanced/control_flow/ for visual explanation
or https://minimal-agent.com for a tutorial on the basic building principles.
"""

import json
import logging
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from mr_deed import Environment, Model, Tool, __version__
from mr_deed.exceptions import Cancelled, FormatError, InterruptAgentFlow, LimitsExceeded, Submitted, TimeExceeded
from mr_deed.utils.serialize import recursive_merge


class AgentConfig(BaseModel):
    """Check the config files in mr_deed/config for example settings."""

    system_template: str
    """Template for the system message (the first message)."""
    instance_template: str
    """Template for the first user message specifying the task (the second message overall)."""
    continue_template: str = "{{ task }}"
    """Template for the user message that continues an existing conversation (see `DefaultAgent.continue_run`)."""
    step_limit: int = 0
    """Maximum number of steps the agent can take (per run or continuation)."""
    cost_limit: float = 3.0
    """Stop agent after exceeding (!) this cost (per run or continuation)."""
    wall_time_limit_seconds: int = 0
    """Stop agent after this many seconds of wall-clock time (per run or continuation). 0 means no limit."""
    max_consecutive_format_errors: int = 3
    """Exit after this many format errors in a row (0 = no limit)."""
    output_path: Path | None = None
    """Save the trajectory to this path."""


class DefaultAgent:
    def __init__(
        self,
        model: Model,
        env: Environment,
        *,
        config_class: type = AgentConfig,
        tools: Sequence[Tool] = (),
        on_event: Callable[[str, dict], Any] | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs,
    ):
        """See the `AgentConfig` class for permitted keyword arguments.

        `tools` are offered to the LM alongside bash (tool-call models only) and may be replaced between runs.
        `on_event(kind, payload)` is called synchronously with every message added to the trajectory
        (kind: system, user, assistant, observation, format_error, exit) and with every `action` before it runs.
        Setting `cancel_event` from any thread stops the run before its next query or action with
        exit_status "Cancelled"; `cancel()` additionally kills the command currently executing.
        """
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.tools = list(tools)
        self.on_event = on_event or (lambda kind, payload: None)
        self.cancel_event = cancel_event or threading.Event()
        self.extra_template_vars = {}
        self.logger = logging.getLogger("agent")
        self.cost = 0.0
        """Cost of the current run or continuation (what the limits apply to); see `total_cost`."""
        self.n_calls = 0
        self.total_cost = 0.0
        """Cost across all runs and continuations of this conversation."""
        self.total_n_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()

    @classmethod
    def from_trajectory(cls, path: Path, model: Model, env: Environment, **kwargs):
        """Restore a conversation saved by `save()` (messages, config, cumulative stats) so it can be continued
        with `continue_run`. Keyword arguments (config values, `tools`, `on_event`, ...) override the saved ones.
        """
        data = json.loads(Path(path).read_text())
        agent = cls(model, env, **(data["info"]["config"]["agent"] | kwargs))
        agent.messages = data["messages"]
        agent.total_cost = data["info"]["model_stats"]["instance_cost"]
        agent.total_n_calls = data["info"]["model_stats"]["api_calls"]
        return agent

    def get_template_vars(self, **kwargs) -> dict:
        return recursive_merge(
            self.config.model_dump(),
            self.env.get_template_vars(),
            self.model.get_template_vars(),
            {
                "n_model_calls": self.n_calls,
                "model_cost": self.cost,
                "elapsed_seconds": int(time.time() - self._start_time),
            },
            self.extra_template_vars,
            kwargs,
        )

    def _render_template(self, template: str) -> str:
        return Template(template, undefined=StrictUndefined).render(**self.get_template_vars())

    def add_messages(self, *messages: dict, kind: str = "") -> list[dict]:
        """Append messages to the trajectory and emit one event each (`kind` defaults to the message's role)."""
        self.logger.debug(messages)  # set log level to debug to see
        self.messages.extend(messages)
        for message in messages:
            self.on_event(kind or message.get("role", "unknown"), message)
        return list(messages)

    def handle_uncaught_exception(self, e: Exception) -> list[dict]:
        return self.add_messages(
            self.model.format_message(
                role="exit",
                content=str(e),
                extra={
                    "exit_status": type(e).__name__,
                    "submission": "",
                    "exception_str": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        )

    def run(self, task: str = "", **kwargs) -> dict:
        """Start a new conversation and run step() until the agent is finished.
        Returns dictionary with exit_status, submission keys."""
        self.messages = []
        self._start_run(task, **kwargs)
        self.add_messages(
            self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
            self.model.format_message(role="user", content=self._render_template(self.config.instance_template)),
        )
        return self._run_steps()

    def continue_run(self, task: str = "", **kwargs) -> dict:
        """Continue the conversation in `messages` (from a previous run or `from_trajectory`) with a new user
        prompt rendered from `continue_template`. Step, cost and time limits start over for this run."""
        self._start_run(task, **kwargs)
        self.add_messages(
            self.model.format_message(role="user", content=self._render_template(self.config.continue_template))
        )
        return self._run_steps()

    def _start_run(self, task: str, **kwargs) -> None:
        self.extra_template_vars |= {"task": task, **kwargs}
        self.cost, self.n_calls, self.n_consecutive_format_errors, self._start_time = 0.0, 0, 0, time.time()
        if reset_interrupt := getattr(self.env, "reset_interrupt", None):
            reset_interrupt()  # a cancel of an earlier run must not kill this run's first command

    def _run_steps(self) -> dict:
        while True:
            try:
                self.step()
                self.n_consecutive_format_errors = 0  # reset on any clean step
            except FormatError as e:
                # The call was billed before parsing failed, so query() never got to charge it.
                self._add_cost(e.messages[0].get("extra", {}).get("cost", 0.0))
                self.n_consecutive_format_errors += 1
                self.add_messages(*e.messages, kind="format_error")
                if 0 < self.config.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                    self.add_messages(
                        {
                            "role": "exit",
                            "content": "RepeatedFormatError",
                            "extra": {"exit_status": "RepeatedFormatError", "submission": ""},
                        }
                    )
            except InterruptAgentFlow as e:
                self.add_messages(*e.messages)
            except Exception as e:
                self.handle_uncaught_exception(e)
                raise
            finally:
                self.save(self.config.output_path)
            if self.messages[-1].get("role") == "exit":
                break
        return self.messages[-1].get("extra", {})

    def step(self) -> list[dict]:
        """Query the LM, execute actions."""
        return self.execute_actions(self.query())

    def query(self) -> dict:
        """Query the model and return model messages. Override to add hooks."""
        self._raise_if_cancelled()
        if 0 < self.config.step_limit <= self.n_calls or 0 < self.config.cost_limit <= self.cost:
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "LimitsExceeded",
                    "extra": {"exit_status": "LimitsExceeded", "submission": ""},
                }
            )
        if 0 < self.config.wall_time_limit_seconds <= int(time.time() - self._start_time):
            raise TimeExceeded(
                {
                    "role": "exit",
                    "content": "TimeExceeded",
                    "extra": {"exit_status": "TimeExceeded", "submission": ""},
                }
            )
        self.n_calls += 1
        self.total_n_calls += 1
        # Exit records of earlier runs stay in the trajectory but are not part of the conversation
        message = self.model.query([m for m in self.messages if m.get("role") != "exit"], tools=self.tools)
        self._add_cost(message.get("extra", {}).get("cost", 0.0))
        self.add_messages(message, kind="assistant")
        return message

    def _add_cost(self, cost: float) -> None:
        self.cost += cost
        self.total_cost += cost

    def cancel(self) -> None:
        """Stop the run from another thread: the next query or action exits with exit_status "Cancelled" and the
        command currently executing (or about to start) is killed if the environment supports `interrupt()`."""
        self.cancel_event.set()
        if interrupt := getattr(self.env, "interrupt", None):
            interrupt()

    def _raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled(
                {"role": "exit", "content": "Cancelled", "extra": {"exit_status": "Cancelled", "submission": ""}}
            )

    def execute_actions(self, message: dict) -> list[dict]:
        """Execute actions in message, add observation messages, return them. Observations are added even when an
        action ends the run, so every tool call has its result if the conversation is continued later."""
        outputs = []
        try:
            for action in message.get("extra", {}).get("actions", []):
                outputs.append(self.execute_action(action))
        except Submitted as e:
            outputs.append({"output": e.messages[0]["content"], "returncode": 0, "exception_info": ""})
            raise
        finally:
            observations = self.add_messages(
                *self.model.format_observation_messages(message, outputs, self.get_template_vars()), kind="observation"
            )
        return observations

    def execute_action(self, action: dict) -> dict:
        """Execute a single action: `bash` in the environment, any other tool name through its `Tool.handler`
        (which only needs to return `output`; `returncode` defaults to 0). Like a failing bash command, a handler
        that raises becomes an observation with returncode -1 instead of ending the run."""
        self._raise_if_cancelled()
        self.on_event("action", action)
        if (name := action.get("name", "bash")) == "bash":
            return self.env.execute(action)
        handler = {tool.name: tool.handler for tool in self.tools}[name]
        try:
            return {"output": "", "returncode": 0, "exception_info": ""} | handler(action["arguments"])
        except InterruptAgentFlow:
            raise  # handlers may deliberately submit or interrupt
        except Exception as e:
            return {"output": "", "returncode": -1, "exception_info": f"{type(e).__name__}: {e}"}

    def serialize(self, *extra_dicts) -> dict:
        """Serialize agent state to a json-compatible nested dictionary for saving."""
        last_message = self.messages[-1] if self.messages else {}
        last_extra = last_message.get("extra", {})
        agent_data = {
            "info": {
                "model_stats": {
                    "instance_cost": self.total_cost,
                    "api_calls": self.total_n_calls,
                },
                "config": {
                    "agent": self.config.model_dump(mode="json"),
                    "agent_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
                "mini_version": __version__,
                "exit_status": last_extra.get("exit_status", ""),
                "submission": last_extra.get("submission", ""),
            },
            "messages": self.messages,
            "trajectory_format": "mr-deed-1.1",
        }
        return recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)

    def save(self, path: Path | None, *extra_dicts) -> dict:
        """Save the trajectory of the agent to a file if path is given. Returns full serialized data.
        You can pass additional dictionaries with extra data to be (recursively) merged into the output data.
        """
        data = self.serialize(*extra_dicts)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        return data
