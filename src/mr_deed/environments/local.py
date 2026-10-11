import os
import platform
import signal
import subprocess
from contextlib import suppress
from typing import Any

from pydantic import BaseModel

from mr_deed.exceptions import Submitted
from mr_deed.utils.serialize import recursive_merge


class LocalEnvironmentConfig(BaseModel):
    cwd: str = ""
    env: dict[str, str] = {}
    timeout: int = 30


class LocalEnvironment:
    def __init__(self, *, config_class: type = LocalEnvironmentConfig, **kwargs):
        """This class executes bash commands directly on the local machine."""
        self.config = config_class(**kwargs)
        self._process: subprocess.Popen | None = None

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        """Execute a command in the local environment and return the result as a dict."""
        command = action.get("command", "")
        cwd = cwd or self.config.cwd or os.getcwd()
        try:
            result = self._run(command, cwd, os.environ | self.config.env, timeout or self.config.timeout)
            output = {"output": result.stdout, "returncode": result.returncode, "exception_info": ""}
        except Exception as e:
            raw_output = getattr(e, "output", None)
            raw_output = (
                raw_output.decode("utf-8", errors="replace") if isinstance(raw_output, bytes) else (raw_output or "")
            )
            output = {
                "output": raw_output,
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {e}",
                "extra": {"exception_type": type(e).__name__, "exception": str(e)},
            }
        self._check_finished(output)
        return output

    def interrupt(self) -> None:
        """Kill the command currently executing, if any. Safe to call from another thread (see `DefaultAgent.cancel`);
        `execute` then returns the partial output with the kill signal's return code."""
        if process := self._process:
            with suppress(ProcessLookupError):  # the command finished in the meantime
                _kill_process_group(process)

    def _check_finished(self, output: dict):
        """Raises Submitted if the output indicates task completion."""
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" and output["returncode"] == 0:
            submission = "".join(lines[1:])
            raise Submitted(
                {
                    "role": "exit",
                    "content": submission,
                    "extra": {"exit_status": "Submitted", "submission": submission},
                }
            )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return recursive_merge(self.config.model_dump(), platform.uname()._asdict(), os.environ, kwargs)

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": self.config.model_dump(mode="json"),
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }

    def _run(self, command: str, cwd: str, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
        """Like subprocess.run, but kills the whole process group on timeout so no children are orphaned."""
        self._process = process = subprocess.Popen(
            command,
            shell=True,
            text=True,
            cwd=cwd,
            env=env,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            stdout, _ = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout)
        finally:
            self._process = None
        return subprocess.CompletedProcess(command, process.returncode, stdout=stdout)


def _kill_process_group(process: subprocess.Popen) -> None:
    os.killpg(process.pid, signal.SIGKILL) if os.name == "posix" else process.kill()
