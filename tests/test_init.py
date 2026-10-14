"""Tests for mr_deed.__init__ and the import-time behavior of the CLI package mr_deed.run."""

import os
import subprocess
import sys


def test_startup_banner_survives_non_utf8_stdout(tmp_path):
    """Importing the CLI package must not crash when stdout can't encode the startup banner (e.g. Windows cp1252)."""
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "MRDEED_SILENT_STARTUP": "",
        "MRDEED_GLOBAL_CONFIG_DIR": str(tmp_path),
    }
    result = subprocess.run([sys.executable, "-c", "import mr_deed.run"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr


def _import_and_print_env(tmp_path, module: str, var: str, extra_env: dict) -> str:
    env = {**os.environ, "MRDEED_SILENT_STARTUP": "1", "MRDEED_GLOBAL_CONFIG_DIR": str(tmp_path / "global")}
    env.pop(var, None)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}, os; print(os.environ.get({var!r}))"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_library_import_does_not_touch_the_environment(tmp_path):
    """Embedding hosts import the library; neither the cwd `.env` nor the global config file may leak into os.environ."""
    (tmp_path / ".env").write_text("MRDEED_TEST_DOTENV_PROBE=from-local-dotenv\n")
    (tmp_path / "global").mkdir()
    (tmp_path / "global" / ".env").write_text("MRDEED_TEST_DOTENV_PROBE=from-global-config\n")

    assert _import_and_print_env(tmp_path, "mr_deed", "MRDEED_TEST_DOTENV_PROBE", {}) == "None"
    assert _import_and_print_env(tmp_path, "mr_deed.agents.default", "MRDEED_TEST_DOTENV_PROBE", {}) == "None"


def test_cli_package_loads_global_config_and_local_env_file(tmp_path):
    """The CLI entry points load the global config file and a project-local .env (e.g. copied from .env.example)."""
    (tmp_path / ".env").write_text("MRDEED_TEST_DOTENV_PROBE=from-local-dotenv\n")
    (tmp_path / "global").mkdir()
    (tmp_path / "global" / ".env").write_text("MRDEED_TEST_GLOBAL_PROBE=from-global-config\n")

    assert _import_and_print_env(tmp_path, "mr_deed.run", "MRDEED_TEST_DOTENV_PROBE", {}) == "from-local-dotenv"
    assert _import_and_print_env(tmp_path, "mr_deed.run", "MRDEED_TEST_GLOBAL_PROBE", {}) == "from-global-config"


def test_local_env_file_does_not_override_the_shell_environment(tmp_path):
    """An already-exported env var must win over the project-local .env (python-dotenv's default behavior)."""
    (tmp_path / ".env").write_text("MRDEED_TEST_DOTENV_PROBE=from-local-dotenv\n")

    probe = {"MRDEED_TEST_DOTENV_PROBE": "from-shell"}
    assert _import_and_print_env(tmp_path, "mr_deed.run", "MRDEED_TEST_DOTENV_PROBE", probe) == "from-shell"
