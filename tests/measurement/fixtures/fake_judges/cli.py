#!/usr/bin/env python3
"""Offline subscription-CLI stand-in; controls and captures live in pytest tmp dirs."""

import json
import pathlib
import sys
import os
import signal
import subprocess

root = pathlib.Path(__file__).parent

if sys.argv[1:2] == ["--hold-stdout"]:
    signal.signal(signal.SIGTERM, lambda *_: (root / "descendant.term").touch())
    (root / "descendant.pid").write_text(str(os.getpid()))
    ready_fd = int(sys.argv[2])
    os.write(ready_fd, b"1")
    os.close(ready_fd)
    while True:
        signal.pause()

provider = pathlib.Path(__file__).name
control = json.loads((root / "control.json").read_text())[provider]
args = sys.argv[1:]


def discovery():
    home = pathlib.Path(os.environ["HOME"])
    config = pathlib.Path(
        os.environ.get(
            "CODEX_HOME" if provider == "codex" else "CLAUDE_CONFIG_DIR",
            str(home / (".codex" if provider == "codex" else ".claude")),
        )
    )
    found = []
    if provider == "codex":
        candidates = [config / "AGENTS.md"]
        if "project_doc_max_bytes=0" not in args:
            candidates += [p / "AGENTS.md" for p in pathlib.Path.cwd().parents]
    else:
        candidates = (
            []
            if "--safe-mode" in args
            else [
                home / ".claude" / "CLAUDE.md",
                config / "CLAUDE.md",
            ]
        )
        settings = (
            json.loads(args[args.index("--settings") + 1])
            if "--settings" in args
            else {}
        )
        if settings.get("autoMemoryEnabled") is not False:
            candidates += list((config / "projects").glob("*/memory/MEMORY.md"))
    for path in candidates:
        if path.is_file():
            found.append(path.read_text())
    auth = config / "auth.json"
    return {
        "HOME_mode": home.stat().st_mode & 0o777,
        "CODEX_HOME_mode": config.stat().st_mode & 0o777 if config.is_dir() else None,
        "instructions": found,
        "config_entries": sorted(p.name for p in config.iterdir())
        if config.is_dir()
        else [],
        "auth_link": str(auth.readlink()) if auth.is_symlink() else None,
    }


def hold_stdout():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    read_fd, write_fd = os.pipe()
    subprocess.Popen(
        [
            sys.executable,
            __file__,
            "--hold-stdout",
            str(write_fd),
        ],
        stdin=subprocess.DEVNULL,
        pass_fds=(write_fd,),
    )
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as ready:
        assert ready.read(1) == b"1"
    (root / "leader.pid").write_text(str(os.getpid()))
    (root / "ready").touch()
    if control.get("leader_exits"):
        sys.exit(0)
    while True:
        signal.pause()


if args == control.get("hang_probe"):
    hold_stdout()
if (
    "--help" in args
    or "--version" in args
    or "status" in args
    or args == ["features", "list"]
):
    probe = {"provider": provider, "args": args}
    if args == ["features", "list"]:
        probe.update(cwd=os.getcwd(), env=dict(os.environ))
    with (root / "probes.jsonl").open("a") as stream:
        stream.write(json.dumps(probe) + "\n")
if args == ["features", "list"]:
    print(control.get("features", (root / "codex-features.txt").read_text()))
    sys.exit(0)
if args == ["login", "status"] or args == ["auth", "status", "--json"]:
    default = (
        "Logged in using ChatGPT"
        if provider == "codex"
        else json.dumps(
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "apiProvider": "firstParty",
                "subscriptionType": "max",
            }
        )
    )
    if control.get("require_auth_link") and not discovery()["auth_link"]:
        sys.exit(1)
    print(
        control.get("auth_status", default),
        file=sys.stderr if provider == "codex" else sys.stdout,
    )
    sys.exit(control.get("auth_exit", 0))
if "--help" in args:
    if args == ["auth", "--help"]:
        print(control.get("auth_help", "status [options] Show authentication status"))
        sys.exit(0)
    if args == ["auth", "status", "--help"]:
        print(control.get("status_help", "--json Output as JSON (default)"))
        sys.exit(0)
    print(
        control.get(
            "help",
            {
                "codex": "exec --model --sandbox --ephemeral --skip-git-repo-check "
                "--ignore-user-config --ignore-rules --output-schema --output-last-message "
                "--disable --config",
                "claude": "-p --model --output-format --json-schema --tools --no-session-persistence "
                "--strict-mcp-config --mcp-config --setting-sources --settings "
                "--safe-mode --disable-slash-commands --permission-mode auth",
            }[provider],
        )
    )
    sys.exit(0)
if "--version" in args:
    print(provider + " fixture-1")
    sys.exit(0)
packet = sys.stdin.read()
with (root / "calls.jsonl").open("a") as stream:
    stream.write(
        json.dumps(
            {
                "provider": provider,
                "args": args,
                "stdin": packet,
                "cwd": os.getcwd(),
                "env": dict(os.environ),
                "discovery": discovery(),
            }
        )
        + "\n"
    )
if control.get("descendant"):
    hold_stdout()
if control.get("block"):
    (root / "leader.pid").write_text(str(os.getpid()))
    (root / "ready").touch()
    while True:
        signal.pause()
if control.get("exit"):
    sys.exit(control["exit"])
response = control.get("response", {"judgments": []})
raw = control.get("raw", json.dumps(response))
if provider == "codex":
    pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(raw)
    print('{"type":"thread.started","thread_id":"fake"}')
else:
    print(
        control.get(
            "raw_envelope",
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "structured_output": response,
                }
            ),
        )
    )
