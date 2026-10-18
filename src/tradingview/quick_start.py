from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from typing import Any, Callable, Sequence

from ._types import AttrDict

LANDING_URL = "https://molted.studio/dreams/market-watch-alerts"
PACKAGE_SPEC = "@mathieuc/tradingview"
AGENT_PROMPT = f"""Help me build a project using TradingView-API V4 ({PACKAGE_SPEC}).
First ask what I want to build and inspect the current project and its instructions before making changes.
Read https://github.com/Mathieu2301/TradingView-API/blob/main/llms.txt and the data API guide at https://github.com/Mathieu2301/TradingView-API/blob/main/docs/data-api.md; use the docs shipped with the installed package as the version-specific reference.
Use Node.js 20+ and install {PACKAGE_SPEC} with the project's package manager. V4 is the default release; use the migration guide before upgrading a V3 project.
Preserve existing files and project configuration. For a new project, start with a small runnable ESM (.mjs) example using getCandles from '@mathieuc/tradingview/data' and anonymous BINANCE:BTCUSDT data, then adapt it to my goal.
Use timeouts, handle errors, and stop watchers or close clients on shutdown. Run the example and report observed results honestly, with exact commands to run it again.
Only request TradingView credentials if my feature needs them; keep them in local environment variables, out of source control and logs. Explain any account or market-data limitations relevant to my goal.
This is an independent community library, not an official TradingView API. Do not assume it provides broker order execution."""

HELP = f"""TradingView-API quick-start (Node.js 20+)

Usage: npx @mathieuc/tradingview [--choice 1|2|3|4|5]

1. Autonomous agent (recommended)
2. Claude Code CLI
3. Codex CLI
4. Another local coding agent
5. Install the library only

Run inside your project directory. Options 2 and 3 require an installed,
authenticated CLI and keep its normal permission prompts. Option 5 runs
npm install {PACKAGE_SPEC} in the current directory.
Use --choice for non-interactive selection; --help shows this message.
"""


def _default_run(command: str, args: list[str], options: dict[str, Any]) -> AttrDict:
    try:
        completed = subprocess.run(
            [command, *args],
            env=options.get("env"),
            timeout=(options.get("timeout", 0) / 1000.0) if options.get("timeout") else None,
            stdout=subprocess.DEVNULL if options.get("stdio") == "ignore" else None,
            stderr=subprocess.DEVNULL if options.get("stdio") == "ignore" else None,
            check=False,
        )
        return AttrDict({"status": completed.returncode, "signal": None, "error": None})
    except BaseException as err:
        return AttrDict({"status": None, "signal": None, "error": err})


def _print_prompt(log: Callable[[str], Any]) -> None:
    log(f"Paste this prompt into your coding agent:\n\n{AGENT_PROMPT}\n")


def _open_landing(runtime: dict[str, Any]) -> int:
    run = runtime["run"]
    log = runtime["log"]
    platform = runtime["platform"]
    env = runtime["env"]
    log(f"Continue with an autonomous agent:\n{LANDING_URL}")
    if platform == "darwin":
        command, args = "open", [LANDING_URL]
    elif platform == "win32":
        command, args = "rundll32.exe", ["url.dll,FileProtocolHandler", LANDING_URL]
    else:
        command, args = "xdg-open", [LANDING_URL]

    result = AttrDict(run(command, args, AttrDict({"stdio": "ignore", "timeout": 10_000, "env": env})))
    if result.get("error") is not None or result.get("status") != 0:
        log("Could not open a browser automatically. Open the link above.")
    return 0


def _launch_local(command: str, runtime: dict[str, Any]) -> int:
    run = runtime["run"]
    log = runtime["log"]
    platform = runtime["platform"]
    env = runtime["env"]
    installing = command == "npm"
    args = ["install", PACKAGE_SPEC] if installing else [AGENT_PROMPT]
    cwd = os.getcwd()
    log(
        f"Installing {PACKAGE_SPEC} in {cwd}..."
        if installing
        else f"Starting {command} in {cwd}..."
    )
    if platform == "win32":
        tail = f"install '{PACKAGE_SPEC}'" if installing else "$env:TRADINGVIEW_QUICK_START_PROMPT"
        ps_cmd = f"$ErrorActionPreference = 'Stop'; & {command} {tail}; exit $LASTEXITCODE"
        child_env = {**dict(env or {}), "TRADINGVIEW_QUICK_START_PROMPT": AGENT_PROMPT}
        result = AttrDict(
            run(
                "powershell.exe",
                ["-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                AttrDict({"stdio": "inherit", "env": AttrDict(child_env)}),
            )
        )
    else:
        result = AttrDict(run(command, args, AttrDict({"stdio": "inherit", "env": env})))

    if result.get("error") is not None or result.get("status") != 0:
        if installing:
            log(f"Installation did not complete. Retry: npm install {PACKAGE_SPEC}")
        else:
            log(f"Could not complete {command}. Ensure its CLI is installed and authenticated, then retry.")
            _print_prompt(log)
        status = result.get("status")
        if status is not None:
            return int(status)
        return 130 if result.get("signal") == "SIGINT" else 1

    if installing:
        log("Library installed. Guide: https://github.com/Mathieu2301/TradingView-API/blob/main/docs/data-api.md")
    return 0


def run_choice(choice: str, overrides: dict[str, Any] | None = None, **kwargs: Any) -> int:
    default_platform = "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")
    runtime: dict[str, Any] = {
        "run": _default_run,
        "log": print,
        "platform": default_platform,
        "env": dict(os.environ),
        **(overrides or {}),
        **kwargs,
    }
    if choice == "1":
        return _open_landing(runtime)
    if choice == "2":
        return _launch_local("claude", runtime)
    if choice == "3":
        return _launch_local("codex", runtime)
    if choice == "4":
        _print_prompt(runtime["log"])
        return 0
    if choice == "5":
        return _launch_local("npm", runtime)
    runtime["log"]("Invalid choice. Choose a number from 1 to 5.")
    return 1


runChoice = run_choice


async def main(args: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    if len(argv) == 1 and argv[0] in ("--help", "-h"):
        print(HELP)
        return 0
    if len(argv) > 0:
        if len(argv) != 2 or argv[0] != "--choice" or not re.match(r"^[1-5]$", argv[1]):
            print(HELP, file=sys.stderr)
            return 1
        return run_choice(argv[1])
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Interactive selection requires a terminal. Use --choice 1|2|3|4|5.", file=sys.stderr)
        return 1
    print(HELP)
    try:
        while True:
            choice = input("Choose an option [1]: ").strip() or "1"
            if re.match(r"^[1-5]$", choice):
                break
            print("Please enter a number from 1 to 5.")
    except (KeyboardInterrupt, EOFError):
        return 130
    return run_choice(choice)


def cli_entry() -> int:
    return asyncio.run(main())


__all__ = [
    "LANDING_URL",
    "PACKAGE_SPEC",
    "AGENT_PROMPT",
    "HELP",
    "run_choice",
    "runChoice",
    "main",
    "cli_entry",
]
