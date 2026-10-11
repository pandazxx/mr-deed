# Embedding mr-deed in a host process

!!! abstract "Overview"

    * This guide is for programs (agent orchestrators, bots, services) that run mr-deed agents in-process
      instead of through the `mini` CLI.
    * It covers continuing a conversation across turns, observing a run live, cancelling it from another
      thread, registering host tools next to `bash`, and what the library guarantees about global state.
    * You should be familiar with the [Python bindings](../usage/python_bindings.md) and the
      [control flow](control_flow.md) of the default agent.

## Importing the library

`import mr_deed` (and the agents, models and environments) has no side effects on your process:
nothing is printed and `os.environ` is left alone.
Only the CLI entry points in `mr_deed.run` load the [global config file](global_configuration.md) and a
project-local `.env` into the environment and print the startup banner, so set API keys and
`MRDEED_*` variables yourself before creating models.

## Continuing a conversation

`DefaultAgent.run(task)` starts a fresh conversation. To pick it up again with a new user prompt, call
`continue_run(task)` on the same agent, or restore the agent from a saved trajectory first:

```python
from pathlib import Path

from mr_deed.agents.default import DefaultAgent
from mr_deed.environments.local import LocalEnvironment
from mr_deed.models import get_model

path = Path("session.traj.json")
agent = DefaultAgent(get_model(), LocalEnvironment(), output_path=path, **config["agent"])
agent.run("Fix the failing test in tests/test_api.py")

# Next turn, possibly in a new process:
agent = DefaultAgent.from_trajectory(path, get_model(), LocalEnvironment())
agent.continue_run("Now also add a regression test.")
```

* The new prompt is rendered from `continue_template` (default `{{ task }}`, extra `run()` keyword
  arguments are template variables as usual) and appended as a `user` message; the system and instance
  templates are not re-rendered.
* `step_limit`, `cost_limit` and `wall_time_limit_seconds` apply **per run or continuation**;
  `agent.n_calls` and `agent.cost` start over. `agent.total_n_calls` and `agent.total_cost` span the
  whole conversation and are what the trajectory records as `model_stats`.
* Every run ends with an `exit` record in `agent.messages`. Those records stay in the trajectory
  (so you can see where each turn ended) but are never sent to the model.
* Every tool call gets an observation, including the one that submitted the previous turn, so the
  continued conversation is valid for strict tool-calling APIs.
* `from_trajectory` restores the saved agent config; keyword arguments override it
  (for example a new `output_path`, `tools` or `on_event`). You can also assign `agent.messages`
  yourself if you keep the history elsewhere.

## Observing a run live

Pass `on_event` to the agent to receive every step synchronously, on the thread that runs the agent:

```python
def on_event(kind: str, payload: dict) -> None:
    print(kind, payload.get("content") or payload)

agent = DefaultAgent(model, env, on_event=on_event, **config["agent"])
```

| kind | when | payload |
| --- | --- | --- |
| `system`, `user` | the system/instance/continuation prompt is added | the message |
| `assistant` | the model answered (including reasoning content, if the API returned any) | the message |
| `action` | right before an action is executed | the action: `name`, its arguments and `tool_call_id` |
| `observation` | an action produced its result (or could not run) | the observation message |
| `format_error` | the model output could not be parsed | the feedback message sent to the model |
| `exit` | the run ended | the exit record; `payload["extra"]["exit_status"]` is one of `Submitted`, `LimitsExceeded`, `TimeExceeded`, `Cancelled`, `RepeatedFormatError` or the name of an uncaught exception, `payload["extra"]["submission"]` the result |

Message payloads are the very dict objects that are appended to `agent.messages`, so the event stream
and the trajectory can never diverge. Exactly one `exit` event is emitted per run or continuation.

## Cancelling a run

Every agent has a `cancel_event` (a `threading.Event`; pass your own to share it). It is checked before
each model query and before each action. Once set, the run stops with `exit_status="Cancelled"` and the
trajectory is saved like for any other exit. `agent.cancel()` sets the event and additionally kills the
command that is currently executing, if the environment supports it:

```python
import threading

agent = DefaultAgent(model, LocalEnvironment(), **config["agent"])
threading.Thread(target=agent.run, args=("Run the whole test suite",)).start()
...
agent.cancel()  # from the UI thread
```

* `LocalEnvironment.interrupt()` kills the whole process group of the running command (the same
  mechanism as the timeout path); the observation records the partial output and the kill signal's
  return code. Other environments finish the current command (or time out) before the agent notices the
  cancellation.
* Cancellation is cooperative: a run that is inside a model request stops right after it returns.
* `cancel()` and `cancel_event.set()` are safe to call from any thread. Clear the event before reusing
  the agent for another run.

## Host tools alongside bash

Tool-call models (the default) can offer additional tools to the model. A tool is a name, a
description, a JSON schema for the arguments and a Python handler:

```python
from mr_deed import Tool

def ask_user(args: dict) -> dict:
    answer = my_ui.ask(args["question"])
    return {"output": answer}

tools = [
    Tool(
        name="ask_user",
        description="Ask the user a clarifying question and wait for the answer.",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        handler=ask_user,
    )
]
agent = DefaultAgent(model, env, tools=tools, **config["agent"])
agent.run(task)
agent.tools = other_tools  # the tool set can change between runs/continuations
agent.continue_run(next_task)
```

* The model is offered `[bash, *agent.tools]` on every query. `bash` stays the primary tool and is
  executed by the environment; every other tool name is routed to its handler by `DefaultAgent.execute_action`.
* The handler receives the parsed arguments (the action without `name` and `tool_call_id`) and returns
  an observation dict: `output` (string) and optionally `returncode` (default 0) and `exception_info`.
  It is rendered with the model's `observation_template` and added to the trajectory like a bash result,
  so the history stays linear and the trajectory format is unchanged.
* Calls to unknown tools, invalid JSON or missing required arguments are reported back to the model as a
  format error instead of crashing the run. Argument names `name` and `tool_call_id` are reserved.
* Host tools are not available with text-based (code-block parsing) models, which raise a `ValueError`
  when given tools.

## Thread safety

* One agent, model and environment instance belong to one run at a time. Run several agents on
  separate threads by giving each its own instances; nothing in a `DefaultAgent` is shared between them.
* Per-agent limits (`cost_limit`, `step_limit`) are enforced by the agent's own counters and never
  depend on what other agents in the process spend.
* `mr_deed.models.GLOBAL_MODEL_STATS` aggregates the cost and call count of all models in the process
  under a lock. Its limits (`MRDEED_GLOBAL_COST_LIMIT`, `MRDEED_GLOBAL_CALL_LIMIT`) are opt-in and off
  by default.
* `on_event` handlers run on the agent's thread; make them non-blocking or hand off to a queue.

## Pinning a version

Every release is tagged `v<version>` (matching `mr_deed.__version__`), so you can pin the git dependency:

```bash
pip install "mr-deed @ git+https://github.com/pandazxx/mr-deed@v0.1.0"
```

Interface-level changes bump the version; the tag is created automatically when the bumped version lands
on `main`.

{% include-markdown "../_footer.md" %}
