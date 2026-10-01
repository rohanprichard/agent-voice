import json

import pytest

from talktome_server.plugins import CODEX_HOOK_EVENTS, Installer, PluginError


class FakeHosts:
    def __init__(self):
        self.calls = []
        self.config = {}

    def run(self, name, *args):
        self.calls.append(" ".join((name, *args)))
        if args[:2] == ("config", "get"):
            if args[2] not in self.config:
                raise PluginError("not set")
            return self.config[args[2]]
        if args[:2] == ("config", "set"):
            self.config[args[2]] = args[3]
        return ""


def installer(tmp_path, *hosts, trust=None):
    for host in hosts:
        (tmp_path / f".{host}").mkdir()
    fake = FakeHosts()
    env = {"TALKTOME_DIR": str(tmp_path / "data")}
    return Installer(
        home=tmp_path, env=env, run=fake.run, exe="/opt/bin/talktome-server", hook_trust=lambda: trust or {}
    ), fake


def test_claude_gets_hooks_that_run_this_program(tmp_path):
    inst, fake = installer(tmp_path, "claude")
    result = inst.install("claude")
    target = tmp_path / ".claude" / "skills" / "talktome"
    hooks = json.loads((target / "hooks" / "hooks.json").read_text())
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == '"/opt/bin/talktome-server" hook claude'
    assert (
        json.loads((target / ".mcp.json").read_text())["mcpServers"]["talktome"]["command"]
        == "/opt/bin/talktome-server"
    )
    assert (target / ".claude-plugin" / "plugin.json").is_file() and (target / "SKILL.md").is_file()
    assert "new Claude Code session" in result["next"]
    assert inst.status("claude") == {"host": "claude", "path": str(target), "installed": True, "current": True}
    assert (tmp_path / "data").is_dir()
    assert fake.calls == []


def test_codex_installs_from_its_own_marketplace_and_reports_trust(tmp_path):
    keys = {f"talktome@talktome:plugin.json#hooks[0]:{e}:0:0": "trusted" for e in CODEX_HOOK_EVENTS}
    inst, fake = installer(tmp_path, "codex", trust=keys)
    inst.install("codex")
    root = tmp_path / ".codex" / "talktome-plugins"
    manifest = (root / "plugins" / "talktome" / ".codex-plugin" / "plugin.json").read_text()
    assert '\\"/opt/bin/talktome-server\\" hook codex' in manifest
    assert json.loads((root / ".agents" / "plugins" / "marketplace.json").read_text())["name"] == "talktome"
    assert f"codex plugin marketplace add {root}" in fake.calls and "codex plugin add talktome@talktome" in fake.calls
    assert inst.status("codex")["hooks_trusted"] is True
    inst.remove("codex")
    assert not root.exists()


def test_hermes_sets_only_the_display_keys_the_user_left_unset(tmp_path):
    inst, fake = installer(tmp_path, "hermes")
    fake.config["display.platforms.talktome.streaming"] = "true"
    result = inst.install("hermes")
    assert "hermes plugins enable talktome" in fake.calls
    assert fake.config["display.platforms.talktome.tool_progress"] == "off"
    assert fake.config["display.platforms.talktome.streaming"] == "true"
    assert "display.platforms.talktome.streaming" not in result["config"]
    assert (tmp_path / ".hermes" / "plugins" / "talktome" / "client.py").is_file()


def test_a_host_that_is_not_set_up_is_reported(tmp_path):
    inst, _ = installer(tmp_path)
    with pytest.raises(PluginError, match="not set up"):
        inst.install("openclaw")


def test_an_install_removes_the_earlier_apps_skill(tmp_path):
    inst, _ = installer(tmp_path, "codex", "hermes")
    old = "---\nname: talktome\ndescription: Start a live voice call through the local TalkToMe app.\n---\n"
    for host in ("codex", "hermes"):
        (tmp_path / f".{host}" / "skills" / "talktome").mkdir(parents=True)
        (tmp_path / f".{host}" / "skills" / "talktome" / "SKILL.md").write_text(old)
    (tmp_path / ".codex" / "skills" / "other").mkdir()
    (tmp_path / ".codex" / "skills" / "other" / "SKILL.md").write_text("an unrelated skill")
    inst.install("codex")
    inst.install("hermes")
    assert not (tmp_path / ".codex" / "skills" / "talktome").exists()
    assert not (tmp_path / ".hermes" / "skills" / "talktome").exists()
    assert (tmp_path / ".codex" / "skills" / "other" / "SKILL.md").exists()


def test_a_plugin_is_not_pointed_into_uvs_cache(tmp_path):
    inst, _ = installer(tmp_path, "claude")
    inst.exe = "/Users/me/.cache/uv/archive-v0/abc/bin/talktome-server"
    with pytest.raises(PluginError, match="uv tool install talktome-server"):
        inst.install("claude")
    assert not (tmp_path / ".claude" / "skills" / "talktome").exists()
