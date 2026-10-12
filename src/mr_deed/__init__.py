"""
This file provides:

- Path settings for global config file & relative directories
- Version numbering
- Protocols for the core components of mr-deed.
  By the magic of protocols & duck typing, you can pretty much ignore them,
  unless you want the static type checking.

Importing this package has no side effects on `os.environ`, stdout or the file system; the CLI entry
points (`mr_deed.run`) create the global config directory, load the config file and print the banner.
"""

__version__ = "0.1.0"

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from platformdirs import user_config_dir

from mr_deed.utils.log import logger

package_dir = Path(__file__).resolve().parent


global_config_dir = Path(os.getenv("MRDEED_GLOBAL_CONFIG_DIR") or user_config_dir("mr-deed"))
global_config_file = Path(global_config_dir) / ".env"


@dataclass
class Tool:
    """A host tool offered to the LM alongside `bash` (tool-call models only, see `DefaultAgent`).
    The agent calls `handler` with the tool call's arguments; the returned dict (`output`, `returncode`,
    optionally `exception_info`) becomes a regular observation message.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    """JSON schema of the arguments."""
    handler: Callable[[dict], dict]


# === Protocols ===
# You can ignore them unless you want static type checking.


class Model(Protocol):
    """Protocol for language models."""

    config: Any

    def query(self, messages: list[dict[str, str]], *, tools: Sequence[Tool] = (), **kwargs) -> dict: ...

    def format_message(self, **kwargs) -> dict: ...

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]: ...

    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...

    def serialize(self) -> dict: ...


class Environment(Protocol):
    """Protocol for execution environments. Environments may additionally offer `interrupt()`
    to kill the command currently executing (see `LocalEnvironment` and `DefaultAgent.cancel`)."""

    config: Any

    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]: ...

    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...

    def serialize(self) -> dict: ...


class Agent(Protocol):
    """Protocol for agents."""

    config: Any

    def run(self, task: str, **kwargs) -> dict: ...

    def continue_run(self, task: str, **kwargs) -> dict: ...

    def cancel(self) -> None: ...

    def save(self, path: Path | None, *extra_dicts) -> dict: ...


__all__ = [
    "Agent",
    "Model",
    "Environment",
    "Tool",
    "package_dir",
    "__version__",
    "global_config_file",
    "global_config_dir",
    "logger",
]
