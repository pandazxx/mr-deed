"""Run scripts for mr-deed.

Importing this package (which every CLI entry point does) prints the startup banner unless
`MRDEED_SILENT_STARTUP` is set and loads the global config file and a project-local `.env` into
`os.environ` (never overriding variables that are already set), and creates the global config directory.
Library users who embed mr-deed import the agents/models/environments directly and keep their process untouched.
"""

import os

import dotenv
from rich.console import Console

from mr_deed import __version__, global_config_dir, global_config_file

global_config_dir.mkdir(parents=True, exist_ok=True)
if not os.getenv("MRDEED_SILENT_STARTUP"):
    Console().print(
        f"This is [bold green]mr-deed[/bold green] version [bold green]{__version__}[/bold green].\n"
        f"Check the [bold red]v2 migration guide[/] at [bold red]https://klieret.short.gy/mini-v2-migration[/]\n"
        f"Loading global config from [bold green]'{global_config_file}'[/bold green]",
    )
dotenv.load_dotenv(dotenv_path=global_config_file)
dotenv.load_dotenv()
