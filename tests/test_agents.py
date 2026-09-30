import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from talktome import agents


@pytest.fixture(autouse=True)
def no_path_binaries(monkeypatch):
    """Detection depends only on the fake home, not on what is installed here."""
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)


def test_the_skill_is_installed_where_codex_reads_it(tmp_path):
    report = agents.install_skill(tmp_path)
    target = tmp_path / ".codex" / "skills" / "talktome" / "SKILL.md"
    assert target.is_file()
    # The file half of the step. `installed` also needs the command, which this
    # deliberately does not put in place.
    assert report["skill"] is True
    assert target.read_text() == agents.skill_source().read_text()


def test_an_edited_skill_is_offered_again(tmp_path):
    # An agent following stale instructions is worse than one with none, so a
    # changed skill must not look installed.
    agents.install_skill(tmp_path)
    assert agents.skill_installed(tmp_path) is True
    target = agents.skill_target(tmp_path)
    target.write_text("older instructions\n")
    assert agents.skill_installed(tmp_path) is False
    agents.install_skill(tmp_path)
    assert agents.skill_installed(tmp_path) is True


def test_a_missing_skill_is_reported_rather_than_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "skill_source", lambda: tmp_path / "gone" / "SKILL.md")
    with pytest.raises(ValueError) as error:
        agents.install_skill(tmp_path)
    assert "missing the TalkToMe skill" in str(error.value)
    assert agents.skill_installed(tmp_path) is False


def test_the_skill_says_how_to_ring_in():
    # The skill is the only place an agent learns the command exists.
    text = agents.skill_source().read_text()
    assert "talktome call" in text
    assert "CODEX_THREAD_ID" in text


# ------------------------------------------------------- the command itself


@pytest.fixture(autouse=True)
def safe_command_dirs(tmp_path, monkeypatch):
    """Keep every command in this module inside the temporary directory.

    These tests write a shell script into the first directory that is on PATH.
    `Path.expanduser()` resolves `~` from the environment and not from a patched
    `Path.home`, so without this they write into the real home and
    /opt/homebrew/bin — which is how a test run once left a broken `talktome` in a
    system directory. Making it a fixture means no test has to remember.
    """
    local = tmp_path / "bin" / "local"
    brew = tmp_path / "bin" / "brew"
    monkeypatch.setattr(agents, "COMMAND_DIRS", (str(local), str(brew)))
    # PATH too, so a call that passes no path_env resolves to the sandbox rather
    # than to the real one.
    monkeypatch.setenv("PATH", f"{local}:{brew}:/usr/bin")
    yield local, brew


def command_env(dirs, extra="/usr/bin"):
    local, brew = dirs
    return f"{local}:{brew}:{extra}"


def test_the_command_goes_somewhere_an_agent_will_find_it(tmp_path, safe_command_dirs):
    # The skill tells an agent to run `talktome call`. Putting the skill in place
    # without the command leaves that instruction pointing into the app's own
    # virtual environment, which no terminal has on its PATH.
    local, _brew = safe_command_dirs
    path = agents.install_command(tmp_path, "/app/.venv/bin/python", command_env(safe_command_dirs))
    assert path == local / "talktome"
    assert path.read_text().startswith("#!/bin/sh")
    assert "/app/.venv/bin/python" in path.read_text()
    assert os.access(path, os.X_OK)


def test_nothing_is_written_outside_the_command_directories(tmp_path, safe_command_dirs):
    local, brew = safe_command_dirs
    path_env = command_env(safe_command_dirs)
    agents.install_command(tmp_path, "/app/.venv/bin/python", path_env)
    assert local.is_dir() and brew.is_dir() is False
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["bin/local/talktome"]


def test_the_command_runs_the_interpreter_the_app_runs(tmp_path, safe_command_dirs):
    path_env = command_env(safe_command_dirs)
    path = agents.install_command(tmp_path, "/app/.venv/bin/python", path_env)
    assert 'exec /app/.venv/bin/python -m talktome "$@"' in path.read_text()


def test_a_command_directory_that_is_not_on_path_is_refused(tmp_path, safe_command_dirs):
    # Writing somewhere the shell does not search is worse than saying so: the
    # install would look successful and the skill would still fail.
    with pytest.raises(ValueError) as error:
        agents.install_command(tmp_path, "/usr/bin/python3", "/usr/bin:/bin")
    assert "nowhere to go" in str(error.value)


def test_homebrew_is_used_when_that_is_what_is_on_path(tmp_path, safe_command_dirs):
    _local, brew = safe_command_dirs
    path = agents.install_command(tmp_path, "/usr/bin/python3", f"{brew}:/usr/bin")
    assert path == brew / "talktome"


def test_a_command_is_recognised_however_the_interpreter_is_spelled(
    tmp_path, monkeypatch, safe_command_dirs
):
    # The same interpreter is `python` or `python3` depending on how it was invoked,
    # and sys.executable is not stable between two runs of one virtual environment.
    # Comparing the text reported a command the app had just installed as missing.
    (tmp_path / "bin").mkdir(parents=True)
    real = tmp_path / "bin" / "python3.12"
    real.write_text("#!/bin/sh\n")
    (tmp_path / "bin" / "python").symlink_to(real)
    (tmp_path / "bin" / "python3").symlink_to(real)
    mine = tmp_path / "commands" / "talktome"
    mine.parent.mkdir()
    mine.write_text(
        f'#!/bin/sh\n# Written by TalkToMe\nexec {tmp_path / "bin" / "python"} -m talktome "$@"\n'
    )
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(mine))
    assert (
        agents.command_installed(tmp_path, str(tmp_path / "bin" / "python3"), path_env="/usr/bin")
        is True
    )


def test_a_skill_without_the_command_is_not_installed(tmp_path, monkeypatch, safe_command_dirs):
    # The status is what the connection screen shows, so it has to mean "an agent
    # can do this", not "a file exists".
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    agents.install_skill(tmp_path)
    report = agents.skill_status(tmp_path)
    assert report["skill"] is True
    assert report["command"] is False
    assert report["installed"] is False


def test_both_halves_install_together(tmp_path, monkeypatch, safe_command_dirs):
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(tmp_path / "talktome"))
    (tmp_path / "talktome").write_text(f'exec "{agents.sys.executable}" -m talktome "$@"')
    report = agents.install_skill_and_command(tmp_path)
    assert report["skill"] is True
    assert report["command"] is True
    assert report["installed"] is True


def test_the_skill_tells_an_agent_how_to_recover_when_it_cannot_run_the_command():
    # This text is the agent's only script for a failure, and the first version of
    # it said to reopen the app, which does not install anything: an agent followed
    # it and told the user to do something that could not help.
    text = agents.skill_source().read_text()
    guidance = text.split("## Connection errors")[1]
    assert "install the command from TalkToMe Settings" in guidance
    assert "reopen" not in guidance.lower()
    # The three failures the command can actually produce.
    assert "`talktome` is missing" in guidance
    assert "app is closed" in guidance
    assert "no transcript yet" in guidance


def test_someone_elses_command_is_not_counted_as_installed(tmp_path, monkeypatch, safe_command_dirs):
    # `talktome` is a plausible name for someone else's tool.
    theirs = tmp_path / "bin" / "talktome"
    theirs.parent.mkdir()
    theirs.write_text(f'#!/bin/sh\nexec "{agents.sys.executable}" -m talktome "$@"\n')
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(theirs))
    assert agents.command_installed(tmp_path, agents.sys.executable, path_env="/usr/bin") is False


def test_a_command_for_another_interpreter_is_not_counted_as_installed(
    tmp_path, monkeypatch, safe_command_dirs
):
    # A shim left over from a deleted checkout points at an interpreter that is
    # gone, so it is not an install even though the file is ours.
    mine = tmp_path / "bin" / "talktome"
    mine.parent.mkdir()
    mine.write_text('#!/bin/sh\n# Written by TalkToMe\nexec "/gone/python" -m talktome "$@"\n')
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(mine))
    assert (
        agents.command_installed(tmp_path, "/somewhere/else/python", path_env="/usr/bin") is False
    )


def test_the_skill_is_found_in_a_frozen_build(tmp_path, monkeypatch):
    # A packaged app has no checkout beside it, so the skill is bundled into the
    # server. Without this the connection screen offers an Install that fails with
    # "missing the TalkToMe skill file" — which is what the first packaged build did.
    bundled = tmp_path / "skills" / "talktome"
    bundled.mkdir(parents=True)
    (bundled / "SKILL.md").write_text("bundled skill\n")
    monkeypatch.setattr(agents.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert agents.skill_source() == bundled / "SKILL.md"
    assert agents.skill_installed(tmp_path) is False
    report = agents.install_skill(tmp_path)
    assert report["skill"] is True
    assert agents.skill_target(tmp_path).read_text() == "bundled skill\n"


def test_a_checkout_still_finds_its_own_skill(tmp_path, monkeypatch):
    monkeypatch.delattr(agents.sys, "_MEIPASS", raising=False)
    source = agents.skill_source()
    assert source.is_file(), "the repository's own skill should still resolve"
    assert ".codex" not in str(source)


def test_the_shell_is_asked_where_commands_are_found(monkeypatch):
    # A GUI-launched app inherits launchd's PATH, which has none of these
    # directories. Reporting "nowhere to go" was true of the app and false of the
    # machine, because the agent runs in the user's terminal.
    class Done:
        returncode = 0
        stdout = "/usr/bin\n" + "/Users/x/.local/bin:/usr/bin:/bin\n"
        stderr = ""

    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert agents.login_path(run=lambda *a, **k: Done()) == "/Users/x/.local/bin:/usr/bin:/bin"


def test_a_shell_that_will_not_answer_falls_back_to_the_process(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    def fail(*args, **kwargs):
        raise OSError("no shell")

    assert agents.login_path(run=fail) == "/usr/bin:/bin"


def test_the_login_path_is_asked_again_after_a_short_time(monkeypatch):
    # A folder the user adds to PATH, such as ~/.local/bin in .zshrc, must be
    # found without a restart of the app.
    answers = iter(["/usr/bin:/bin", "/Users/x/.local/bin:/usr/bin:/bin"])
    asked = []

    class Done:
        returncode = 0
        stderr = ""

        def __init__(self):
            self.stdout = next(answers) + "\n"

    def run(*args, **kwargs):
        asked.append(args)
        return Done()

    now = [1000.0]
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(agents, "_LOGIN_PATH", {})
    # Only the real runner is cached, so the fake takes its place.
    monkeypatch.setattr(agents.subprocess, "run", run)
    monkeypatch.setattr(agents.time, "monotonic", lambda: now[0])
    assert agents.login_path(run=run) == "/usr/bin:/bin"
    now[0] += agents.LOGIN_PATH_TTL - 1
    assert agents.login_path(run=run) == "/usr/bin:/bin"
    assert len(asked) == 1
    now[0] += 2
    assert agents.login_path(run=run) == "/Users/x/.local/bin:/usr/bin:/bin"
    assert len(asked) == 2


# ------------------------ finding the agent, not finding this process's PATH


def test_a_command_is_found_through_the_shell_when_this_process_cannot(monkeypatch):
    # This is what the user hit. A packaged app has launchd's PATH, so `which`
    # said Codex was not installed while they were looking at a Codex session, and
    # every spoken word was refused for a reason that was not true.
    monkeypatch.setattr(agents, "login_path", lambda *a, **k: "/Users/x/.local/bin:/usr/bin:/bin")
    monkeypatch.setattr(
        agents.shutil,
        "which",
        lambda name, path=None: f"{path}/codex" if path else None,
    )
    assert agents.find_command("codex") == "/Users/x/.local/bin:/usr/bin:/bin/codex"


def test_a_command_that_is_already_on_this_path_is_not_looked_for_twice(monkeypatch):
    asked = []
    monkeypatch.setattr(
        agents.shutil,
        "which",
        lambda name, path=None: (asked.append(path), "/usr/bin/codex")[1],
    )
    assert agents.find_command("codex") == "/usr/bin/codex"
    assert asked == [None]


def test_a_command_that_is_not_there_is_asked_again_next_time(monkeypatch):
    # Only hits are kept. If a miss were remembered, installing the agent while the
    # app is open would stay invisible until it was restarted.
    agents._FOUND.clear()
    monkeypatch.setattr(agents, "login_path", lambda *a, **k: "/usr/bin:/bin")
    monkeypatch.setattr(agents.shutil, "which", lambda name, path=None: None)
    assert agents.find_command("codex") is None
    monkeypatch.setattr(
        agents.shutil, "which", lambda name, path=None: "/now/installed/codex" if path else None
    )
    assert agents.find_command("codex") == "/now/installed/codex"


def test_nowhere_to_go_explains_what_to_add(tmp_path, monkeypatch, safe_command_dirs):
    # Failing silently leaves the user stuck. The message has to be something they
    # can act on.
    monkeypatch.setattr(agents, "login_path", lambda *a, **k: "/usr/bin:/bin")
    with pytest.raises(ValueError) as error:
        agents.install_command(tmp_path, "/usr/bin/python3")
    assert "export PATH=" in str(error.value)
    assert ".zshrc" in str(error.value)


# ------------------------------------------------- the command in a packaged app


def fake_app(root, name="TalkToMe.app"):
    """An app folder whose server only reports how it was run."""
    app = root / name
    server = app / agents.SERVER_IN_APP
    server.parent.mkdir(parents=True)
    server.write_text('#!/bin/sh\necho "server $*"\necho "launch $TALKTOME_LAUNCH"\n')
    server.chmod(0o755)
    return app


def run_shim(script, tmp_path, spotlight=""):
    # A stub mdfind comes first on PATH, so no test asks the real Spotlight and
    # finds the real app.
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    mdfind = stubs / "mdfind"
    mdfind.write_text(f"#!/bin/sh\nprintf '%s' {shlex.quote(spotlight)}\n")
    mdfind.chmod(0o755)
    shim = tmp_path / "shim"
    shim.write_text(script)
    shim.chmod(0o755)
    return subprocess.run(
        [str(shim), "call", "--agent", "claude"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(tmp_path / "home")},
        timeout=10,
    )


def test_a_packaged_command_does_not_hold_the_path_of_the_app(tmp_path, safe_command_dirs):
    # The path at install time breaks when the user moves the app.
    python = f"/Users/x/Downloads/TalkToMe.app/{agents.SERVER_IN_APP}"
    path = agents.install_command(tmp_path, python, command_env(safe_command_dirs))
    text = path.read_text()
    assert "Downloads" not in text
    assert agents.APP_ID in text
    assert '"/Applications/TalkToMe.app" "$HOME/Applications/TalkToMe.app"' in text
    assert agents.is_our_command(path)


def test_a_packaged_command_finds_the_app_where_it_is_now(tmp_path):
    app = fake_app(tmp_path / "Applications")
    script = agents.command_script(f"/old/TalkToMe.app/{agents.SERVER_IN_APP}", apps=(str(app),))
    result = run_shim(script, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "server -m talktome call --agent claude",
        f'launch open -g -a "{app}"',
    ]


def test_a_packaged_command_asks_spotlight_when_the_app_is_elsewhere(tmp_path):
    moved = fake_app(tmp_path / "Somewhere else")
    translocated = fake_app(tmp_path / "AppTranslocation" / "ABC")
    script = agents.command_script(
        f"/old/TalkToMe.app/{agents.SERVER_IN_APP}", apps=(str(tmp_path / "gone.app"),)
    )
    # A mounted disk image is never used either, because it goes away on eject.
    spotlight = f"/Volumes/TalkToMe 0.1.0-arm64/TalkToMe.app\n{translocated}\n{moved}\n"
    result = run_shim(script, tmp_path, spotlight=spotlight)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1] == f'launch open -g -a "{moved}"'


def test_a_packaged_command_says_so_when_the_app_is_gone(tmp_path):
    script = agents.command_script(
        f"/old/TalkToMe.app/{agents.SERVER_IN_APP}", apps=(str(tmp_path / "gone.app"),)
    )
    result = run_shim(script, tmp_path)
    assert result.returncode == 1
    assert "Move TalkToMe to the Applications folder" in result.stderr


@pytest.mark.parametrize(
    "app",
    [
        # Opened from Downloads: macOS runs a random copy that is gone after it quits.
        "/private/var/folders/x/T/AppTranslocation/1234/d/TalkToMe.app",
        # Opened from the disk image: gone after it is ejected. The owner hit this.
        "/Volumes/TalkToMe 0.1.0-arm64/TalkToMe.app",
    ],
)
def test_an_app_in_a_temporary_place_does_not_write_a_command(tmp_path, safe_command_dirs, app):
    with pytest.raises(ValueError) as error:
        agents.install_command(
            tmp_path, f"{app}/{agents.SERVER_IN_APP}", command_env(safe_command_dirs)
        )
    assert str(error.value) == "Move TalkToMe to Applications first, then install the command."
    local, brew = safe_command_dirs
    assert not (local / "talktome").exists() and not (brew / "talktome").exists()


def test_a_checkout_launched_from_a_translocated_path_is_refused(tmp_path, safe_command_dirs):
    with pytest.raises(ValueError):
        agents.install_command(
            tmp_path,
            "/app/.venv/bin/python",
            command_env(safe_command_dirs),
            launcher='open -g -a "/private/var/folders/x/T/AppTranslocation/1/d/TalkToMe.app"',
        )


def test_a_checkout_on_an_external_disk_still_installs(tmp_path, safe_command_dirs):
    path = agents.install_command(
        tmp_path, "/Volumes/Code/talktome/.venv/bin/python", command_env(safe_command_dirs)
    )
    assert 'exec /Volumes/Code/talktome/.venv/bin/python -m' in path.read_text()


def test_a_packaged_app_counts_only_the_command_that_looks_it_up(tmp_path, safe_command_dirs):
    path_env = command_env(safe_command_dirs)
    python = f"/Applications/TalkToMe.app/{agents.SERVER_IN_APP}"
    path = agents.install_command(tmp_path, python, path_env)
    assert agents.command_installed(tmp_path, python, path_env) is True
    # A copy of the app somewhere else is served by the same command.
    other = f"/Users/x/Applications/TalkToMe.app/{agents.SERVER_IN_APP}"
    assert agents.command_installed(tmp_path, other, path_env) is True
    # The older form held one copy's path, and it is offered again.
    path.write_text(f'#!/bin/sh\n# Written by TalkToMe\nexec "{python}" -m talktome "$@"\n')
    assert agents.command_installed(tmp_path, python, path_env) is False


def test_a_checkout_keeps_its_own_interpreter(tmp_path, safe_command_dirs):
    path_env = command_env(safe_command_dirs)
    path = agents.install_command(
        tmp_path, "/repo/.venv/bin/python", path_env, launcher='"/e/Electron" "/repo"'
    )
    text = path.read_text()
    assert 'exec /repo/.venv/bin/python -m talktome "$@"' in text
    assert "export TALKTOME_LAUNCH='\"/e/Electron\" \"/repo\"'" in text
    assert "mdfind" not in text


def test_a_system_folder_is_left_for_the_administrator_prompt(
    tmp_path, monkeypatch, safe_command_dirs
):
    # A Mac without Homebrew has /usr/local/bin on PATH, owned by root. The
    # desktop app writes the script there after an administrator prompt.
    local = tmp_path / "bin" / "local"
    system = tmp_path / "bin" / "system"
    system.mkdir(parents=True)
    system.chmod(0o555)
    monkeypatch.setattr(agents, "COMMAND_DIRS", (str(local), str(system)))
    monkeypatch.setattr(agents, "SYSTEM_COMMAND_DIR", str(system))
    try:
        assert agents.needs_admin(f"{system}:/usr/bin") is True
        with pytest.raises(ValueError) as error:
            agents.install_command(tmp_path, "/repo/.venv/bin/python", f"{system}:/usr/bin")
        assert "Install for all users" in str(error.value)
        assert not (system / "talktome").exists()
        # A user folder on PATH is used before any administrator prompt.
        path_env = f"{local}:{system}"
        assert agents.needs_admin(path_env) is False
        assert agents.install_command(tmp_path, "/repo/.venv/bin/python", path_env).parent == local
    finally:
        system.chmod(0o755)


def test_the_skill_goes_to_claude_code_when_it_is_there(tmp_path):
    assert "claude" not in agents.skill_targets(tmp_path)
    (tmp_path / ".claude").mkdir()
    target = tmp_path / ".claude" / "skills" / "talktome" / "SKILL.md"
    assert agents.skill_targets(tmp_path)["claude"] == target
    report = agents.install_skill(tmp_path)
    assert target.read_text() == agents.skill_source().read_text()
    assert {"id": "claude", "path": str(target), "skill": True} in report["hosts"]
    agents.uninstall_skill(tmp_path)
    assert not target.parent.exists()
    assert not agents.skill_target(tmp_path).exists()
    assert (tmp_path / ".claude").is_dir()


def test_the_skill_goes_to_the_hermes_home_that_hermes_names(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(profile))
    assert agents.skill_targets(tmp_path)["hermes"] == profile / "skills" / "talktome" / "SKILL.md"


def test_the_skill_sends_a_paired_server_across_the_bridge():
    # A Hermes agent on a server once read "run the commands on the Mac", went
    # looking for a telephony tool, and then tried to build TalkToMe to learn how.
    text = agents.skill_source().read_text()
    description = text.split("description:")[1].split("\n")[0]
    assert "not a phone call" in description
    assert "remote bridge" in description
    local_or_remote = text.split("## Local or remote")[1].split("\n## ")[0]
    assert "talktome remote-status" in local_or_remote
    assert "add `--remote`" in local_or_remote


def test_the_skill_offers_a_call_back_for_long_work():
    # A user who has to stay quiet while the agent works for minutes will hang up.
    text = agents.skill_source().read_text()
    section = text.split("## Do not keep the user waiting")[1].split("\n## ")[0]
    assert "I'll call you back when I'm done with that." in section
    assert "background subagent" in section
    assert "--greeting" in section


def test_the_skill_gives_claude_code_a_cooperative_call():
    # Claude Code has no terminal adapter, so its call must be cooperative. The
    # server makes `--agent claude` cooperative without the flag.
    text = agents.skill_source().read_text()
    assert "talktome call --agent claude --thread SESSION_ID" in text
    assert "| Claude Code | Cooperative commands in this session |" in text


def test_the_dev_shim_runs_from_a_path_the_shell_would_expand(tmp_path):
    folder = tmp_path / 'odd "$HOME" folder'
    folder.mkdir()
    python = folder / "python"
    python.write_text('#!/bin/sh\necho "ran $*"\n')
    python.chmod(0o755)
    shim = tmp_path / "talktome"
    shim.write_text(agents.command_script(str(python)))
    result = subprocess.run(["/bin/sh", str(shim), "call"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ran -m talktome call"


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="needs Node.js")
@pytest.mark.parametrize(
    ("python", "launcher"),
    [
        (f"/Applications/TalkToMe.app/{agents.SERVER_IN_APP}", None),
        ("/Users/me/talktome/.venv/bin/python", '"/e/Electron" "/Users/me/talktome"'),
        ('/Users/me/odd "$dir"/.venv/bin/python', "it's"),
    ],
)
def test_the_desktop_app_builds_the_same_script(python, launcher):
    # The app installs its own copy for all users and never reads the staged file,
    # so the two builders must not drift.
    install = Path(__file__).resolve().parents[1] / "desktop" / "install.cjs"
    program = (
        f"process.stdout.write(require({json.dumps(str(install))})"
        f".commandScript({json.dumps(python)}, {json.dumps(launcher)}))"
    )
    result = subprocess.run([NODE, "-e", program], capture_output=True, text=True, check=True)
    assert result.stdout == agents.command_script(python, launcher)
