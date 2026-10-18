import pytest

from tradingview.quick_start import AGENT_PROMPT, HELP, LANDING_URL, PACKAGE_SPEC, main, runChoice

OK = {"status": 0, "signal": None, "error": None}


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_opens_hosted_path_without_installing(platform):
    commands = []
    messages = []

    def run(cmd, args, _options):
        commands.append(cmd)
        assert LANDING_URL in args
        return OK

    assert runChoice("1", {"platform": platform, "log": messages.append, "run": run}) == 0
    expected_cmd = "xdg-open" if platform == "linux" else ("open" if platform == "darwin" else "rundll32.exe")
    assert commands == [expected_cmd]
    assert LANDING_URL in "\n".join(messages)


def test_leaves_usable_link_when_browser_fails():
    messages = []
    assert (
        runChoice(
            "1",
            {
                "log": messages.append,
                "run": lambda *_: {**OK, "status": None, "error": RuntimeError("ENOENT")},
            },
        )
        == 0
    )
    assert "Open the link above" in "\n".join(messages)


@pytest.mark.parametrize("choice,command", [("2", "claude"), ("3", "codex")])
def test_hands_prompt_to_agent_with_terminal_inheritance(choice, command):
    def run(cmd, args, options):
        assert cmd == command
        assert args == [AGENT_PROMPT]
        assert options["stdio"] == "inherit"
        assert options.get("shell") is None
        return OK

    assert runChoice(choice, {"platform": "linux", "log": lambda *_: None, "run": run}) == 0


@pytest.mark.parametrize("choice", ["2", "3", "5"])
def test_uses_fixed_windows_launcher(choice):
    def run(cmd, args, options):
        assert cmd == "powershell.exe"
        assert AGENT_PROMPT not in " ".join(args)
        assert options["env"]["TRADINGVIEW_QUICK_START_PROMPT"] == AGENT_PROMPT
        expected = f"install '{PACKAGE_SPEC}'" if choice == "5" else "$env:TRADINGVIEW_QUICK_START_PROMPT"
        assert expected in args[-1]
        return OK

    assert runChoice(choice, {"platform": "win32", "log": lambda *_: None, "run": run}) == 0


def test_only_prints_prompt_for_another_agent():
    messages = []

    def must_not_spawn(*_):
        raise RuntimeError("must not spawn")

    assert runChoice("4", {"log": messages.append, "run": must_not_spawn}) == 0
    assert AGENT_PROMPT in "\n".join(messages)


def test_installs_default_v4_package():
    def run(cmd, args, _options):
        assert cmd == "npm"
        assert args == ["install", PACKAGE_SPEC]
        return OK

    assert runChoice("5", {"platform": "linux", "log": lambda *_: None, "run": run}) == 0


def test_preserves_failing_child_exit_status_and_fallback_prompt():
    messages = []
    assert runChoice("2", {"log": messages.append, "run": lambda *_: {**OK, "status": 7}}) == 7
    assert AGENT_PROMPT in "\n".join(messages)


def test_handles_missing_cli_and_interrupted_installation():
    assert (
        runChoice(
            "3",
            {
                "log": lambda *_: None,
                "run": lambda *_: {**OK, "status": None, "error": RuntimeError("ENOENT")},
            },
        )
        == 1
    )
    messages = []
    assert (
        runChoice(
            "5",
            {"log": messages.append, "run": lambda *_: {**OK, "status": None, "signal": "SIGINT"}},
        )
        == 130
    )
    assert "Library installed" not in "\n".join(messages)


def test_rejects_invalid_selections_without_spawning():
    def must_not_spawn(*_):
        raise RuntimeError("must not spawn")

    assert runChoice("6", {"log": lambda *_: None, "run": must_not_spawn}) == 1


@pytest.mark.asyncio
async def test_documents_choices_and_supports_help_and_explicit_prompt_mode():
    assert "Autonomous agent (recommended)" in HELP
    assert await main(["--help"]) == 0
    assert await main(["--choice", "4"]) == 0
    assert await main(["--choice", "6"]) == 1
    assert await main(["--unknown"]) == 1
