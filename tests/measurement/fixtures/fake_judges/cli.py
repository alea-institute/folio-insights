#!/usr/bin/env python3
"""Offline subscription-CLI stand-in; controls and captures live in pytest tmp dirs."""

import json
import pathlib
import sys
import time
import os
import signal
import subprocess

root = pathlib.Path(__file__).parent
provider = pathlib.Path(__file__).name
control = json.loads((root / "control.json").read_text())[provider]
args = sys.argv[1:]


def hold_stdout():
    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os, pathlib, signal, sys, time; "
            "signal.signal(signal.SIGTERM, lambda *_: pathlib.Path(sys.argv[2]).touch()); "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
            "time.sleep(2)",
            str(root / "descendant.pid"),
            str(root / "descendant.term"),
        ],
        stdin=subprocess.DEVNULL,
    )
    while not (root / "descendant.pid").exists():
        time.sleep(0.005)
    if control.get("leader_exits"):
        sys.exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)


if args == control.get("hang_probe"):
    hold_stdout()
if "--help" in args or "--version" in args or "status" in args:
    with (root / "probes.jsonl").open("a") as stream:
        stream.write(json.dumps({"provider": provider, "args": args}) + "\n")
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
            }
        )
        + "\n"
    )
if control.get("descendant"):
    hold_stdout()
time.sleep(control.get("sleep", 0))
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
