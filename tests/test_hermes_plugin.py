"""The Hermes plugin, run against small stand-ins for the Hermes gateway.

The plugin runs inside Hermes and imports its gateway modules, which this
environment does not have. The stand-ins copy only the parts the plugin uses, so
these tests cover the plugin's own turn logic, not Hermes.
"""

import asyncio
import enum
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from talktome import host_plugins

PLUGIN = Path(__file__).resolve().parents[1] / "src" / "talktome" / "plugins" / "hermes"


def load_client():
    spec = importlib.util.spec_from_file_location("hermes_talktome_client", PLUGIN / "client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


client = load_client()


def fake_gateway(monkeypatch):
    @dataclass
    class SendResult:
        success: bool = False
        message_id: str | None = None
        error: str | None = None

    class MessageType(enum.Enum):
        TEXT = "text"

    class ProcessingOutcome(enum.Enum):
        SUCCESS = "success"
        FAILURE = "failure"
        CANCELLED = "cancelled"

    @dataclass
    class MessageEvent:
        text: str
        message_type: Any = None
        source: Any = None
        message_id: str | None = None
        raw_message: Any = None
        timestamp: Any = None

    class BasePlatformAdapter:
        def __init__(self, config, platform):
            self.config = config
            self.platform = platform
            self.handled = []

        def _mark_connected(self):
            pass

        def _mark_disconnected(self):
            pass

        def build_source(self, **fields):
            return types.SimpleNamespace(**fields)

        async def handle_message(self, event):
            self.handled.append(event)

    base = types.ModuleType("gateway.platforms.base")
    base.BasePlatformAdapter = BasePlatformAdapter
    base.MessageEvent = MessageEvent
    base.MessageType = MessageType
    base.ProcessingOutcome = ProcessingOutcome
    base.SendResult = SendResult
    config = types.ModuleType("gateway.config")
    config.Platform = str
    for name, module in {
        "gateway": types.ModuleType("gateway"),
        "gateway.config": config,
        "gateway.platforms": types.ModuleType("gateway.platforms"),
        "gateway.platforms.base": base,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return base


@pytest.fixture
def plugin(monkeypatch):
    base = fake_gateway(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "hermes_talktome", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    package = importlib.util.module_from_spec(spec)
    # Each test gets fresh stand-ins, so the plugin must import them again.
    for name in ("hermes_talktome.adapter", "hermes_talktome.client"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "hermes_talktome", package)
    spec.loader.exec_module(package)
    adapter_module = sys.modules["hermes_talktome.adapter"]
    return types.SimpleNamespace(module=adapter_module, base=base)


@dataclass
class FakeClient:
    remote: bool = True
    replies: list = field(default_factory=list)

    async def reply(self, thread, call_id, turn_id, item_id, text, final):
        self.replies.append((item_id, text, final))
        return {"ok": True}


async def live_turn(plugin, text="What is on my calendar?"):
    adapter = plugin.module.TalkToMeAdapter(types.SimpleNamespace(extra={}))
    fake = FakeClient()
    call = plugin.module.Call(thread="hermes-1", client=fake, source=adapter.build_source(chat_id="hermes-1"))
    adapter._call = call
    await adapter._dispatch(call, {"call_id": "call-1", "turn_id": "turn-1", "text": text})
    return adapter, fake, adapter.handled[-1]


def test_each_spoken_turn_becomes_a_message_in_the_call_chat(plugin):
    async def scenario():
        _, _, event = await live_turn(plugin)
        assert event.text == "What is on my calendar?"
        assert event.source.chat_id == "hermes-1"
        assert event.message_id == "turn-1"

    asyncio.run(scenario())


def test_the_last_message_of_a_turn_is_the_final_reply(plugin):
    # Hermes can say something before a tool call and then answer. Only the
    # answer may end the voice turn, and it is known only when Hermes finishes.
    async def scenario():
        adapter, fake, event = await live_turn(plugin)
        await adapter.send("hermes-1", "Let me **check** that.")
        assert fake.replies == []
        await adapter.send("hermes-1", "You have two meetings.")
        assert fake.replies == [("turn-1-1", "Let me check that.", False)]
        await adapter.on_processing_complete(event, plugin.base.ProcessingOutcome.SUCCESS)
        assert fake.replies[-1] == ("turn-1-final", "You have two meetings.", True)
        # The turn is over, so a late message has nobody to reach.
        await adapter.send("hermes-1", "One more thing.")
        assert len(fake.replies) == 2

    asyncio.run(scenario())


def test_a_failed_turn_still_ends_with_something_spoken(plugin):
    async def scenario():
        adapter, fake, event = await live_turn(plugin)
        await adapter.on_processing_complete(event, plugin.base.ProcessingOutcome.FAILURE)
        assert fake.replies == [("turn-1-final", "Sorry, something went wrong on my side.", True)]

    asyncio.run(scenario())


def test_a_cancelled_turn_speaks_nothing_more(plugin):
    # The user spoke over the reply. The laptop cancels the turn, and the next
    # turn is on its way.
    async def scenario():
        adapter, fake, event = await live_turn(plugin)
        await adapter.send("hermes-1", "Working on it.")
        await adapter._cancelled(adapter._call, "turn-1")
        await adapter.send("hermes-1", "Here is the answer.")
        await adapter.on_processing_complete(event, plugin.base.ProcessingOutcome.CANCELLED)
        assert fake.replies == []

    asyncio.run(scenario())


def test_a_message_for_another_chat_is_not_spoken(plugin):
    async def scenario():
        adapter, fake, event = await live_turn(plugin)
        result = await adapter.send("some-other-chat", "Hello")
        assert result.success
        await adapter.on_processing_complete(event, plugin.base.ProcessingOutcome.SUCCESS)
        assert fake.replies == [("turn-1-final", "", True)]

    asyncio.run(scenario())


def test_an_edit_replaces_the_held_message(plugin):
    async def scenario():
        adapter, fake, event = await live_turn(plugin)
        sent = await adapter.send("hermes-1", "You have")
        await adapter.edit_message("hermes-1", sent.message_id, "You have two meetings.")
        await adapter.on_processing_complete(event, plugin.base.ProcessingOutcome.SUCCESS)
        assert fake.replies == [("turn-1-final", "You have two meetings.", True)]

    asyncio.run(scenario())


def test_markdown_and_code_are_not_read_aloud():
    text = "## Result\n\n- **Disk**: 163 GB free\n- See [the docs](https://x.io)\n```sh\ndf -h\n```\nDone."
    assert client.speakable(text) == "Result Disk: 163 GB free See the docs Done."
    assert client.speakable("Open https://example.com/a now") == "Open a link now"


def test_remote_status_is_read_past_its_inbox_lines():
    output = 'inbox: /x\nfallback inbox: /y\n{"configured": true, "role": "agent"}\n'
    assert client.first_json(output) == {"configured": True, "role": "agent"}
    with pytest.raises(client.TalkToMeError):
        client.first_json("nothing here")


@pytest.fixture
def echo_command(tmp_path):
    script = tmp_path / "talktome"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if 'fail' in sys.argv:\n"
        "    print('The laptop is offline.', file=sys.stderr); sys.exit(1)\n"
        "if 'remote-status' in sys.argv:\n"
        "    print('inbox: /x'); print(json.dumps({'configured': True, 'role': 'agent'})); sys.exit(0)\n"
        "print(json.dumps({'argv': sys.argv[1:]}))\n"
    )
    script.chmod(0o755)
    return str(script)


def test_a_paired_server_sends_every_command_across_the_bridge(echo_command):
    async def scenario():
        found = await client.TalkToMeClient.discover({"TALKTOME_COMMAND": echo_command})
        assert found.remote is True
        argv = (await found.call("hermes-1", "-Hi there", None))["argv"]
        assert argv[:2] == ["--remote", "call"]
        # A greeting that starts with a dash is still one value.
        assert "--greeting=-Hi there" in argv
        assert "--connection" not in argv
        reply = (await found.reply("hermes-1", "c", "t", "i", "Hello", final=False))["argv"]
        assert reply[0] == "--remote" and reply[-1] == "--progress"

    asyncio.run(scenario())


def test_on_the_mac_a_call_is_cooperative(echo_command):
    async def scenario():
        local = await client.TalkToMeClient.discover(
            {"TALKTOME_COMMAND": echo_command, "TALKTOME_REMOTE": "false"}
        )
        argv = (await local.call("hermes-1", "Hi", "Deploy"))["argv"]
        assert argv[0] == "call"
        assert argv[-3:] == ["--connection", "cooperative", "--name=Deploy"]

    asyncio.run(scenario())


def test_a_refused_command_reports_its_last_line(echo_command):
    async def scenario():
        with pytest.raises(client.TalkToMeError, match="The laptop is offline."):
            await client.run(echo_command, ["listen", "fail"], timeout=10)

    asyncio.run(scenario())


# -- installing the plugin --------------------------------------------------------


class FakeHermes:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.calls = []

    def __call__(self, argv, **kwargs):
        args = argv[1:]
        self.calls.append(args)
        out, code = "", 0
        if args[:2] == ["config", "get"]:
            if args[2] in self.config:
                out = self.config[args[2]]
            else:
                out, code = f"Config key not set: {args[2]}", 1
        elif args[:2] == ["config", "set"]:
            self.config[args[2]] = args[3]
        return types.SimpleNamespace(stdout=out, stderr="", returncode=code)


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    (tmp_path / ".hermes").mkdir()
    monkeypatch.setattr(host_plugins, "find_command", lambda name: f"/bin/{name}")
    return tmp_path


def test_install_copies_the_plugin_and_enables_it(hermes_home):
    hermes = FakeHermes()
    report = host_plugins.install("hermes", hermes_home, run=hermes)
    target = hermes_home / ".hermes" / "plugins" / "talktome"
    assert (target / "plugin.yaml").is_file()
    assert (target / "adapter.py").read_text() == (PLUGIN / "adapter.py").read_text()
    assert not (target / "__pycache__").exists()
    assert ["plugins", "enable", "talktome"] in hermes.calls
    assert report["enabled"] is True
    assert host_plugins.status("hermes", hermes_home) == {
        "agent": "hermes",
        "path": str(target),
        "installed": True,
        "current": True,
    }


def test_install_keeps_the_display_settings_the_user_chose(hermes_home):
    # A global `display.tool_progress: all` would read tool lines aloud, so the
    # plugin sets voice values for its own platform, but only where none exist.
    chosen = "display.platforms.talktome.interim_assistant_messages"
    hermes = FakeHermes({chosen: "false"})
    report = host_plugins.install("hermes", hermes_home, run=hermes)
    assert hermes.config["display.platforms.talktome.tool_progress"] == "off"
    assert hermes.config[chosen] == "false"
    assert chosen not in report["config"]


def test_an_edited_plugin_is_not_current(hermes_home):
    host_plugins.install("hermes", hermes_home, run=FakeHermes())
    (hermes_home / ".hermes" / "plugins" / "talktome" / "client.py").write_text("# old\n")
    assert host_plugins.status("hermes", hermes_home)["current"] is False


def test_remove_disables_and_deletes_the_plugin(hermes_home):
    hermes = FakeHermes()
    host_plugins.install("hermes", hermes_home, run=hermes)
    assert host_plugins.remove("hermes", hermes_home, run=hermes)["removed"] is True
    assert ["plugins", "disable", "talktome"] in hermes.calls
    assert not (hermes_home / ".hermes" / "plugins" / "talktome").exists()


def test_install_needs_hermes_to_be_set_up(tmp_path, monkeypatch):
    monkeypatch.setattr(host_plugins, "find_command", lambda name: None)
    with pytest.raises(ValueError, match="not set up"):
        host_plugins.install("hermes", tmp_path)


def test_the_plugin_ships_its_two_tools():
    manifest = (PLUGIN / "plugin.yaml").read_text()
    assert "talktome_call" in manifest and "talktome_end" in manifest
