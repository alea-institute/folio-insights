#!/usr/bin/env python3
"""Offline subscription-CLI stand-in; controls and captures live in pytest tmp dirs."""

import json
import pathlib
import sys
import time
import os

root = pathlib.Path(__file__).parent
provider = pathlib.Path(__file__).name
control = json.loads((root / "control.json").read_text())[provider]
args = sys.argv[1:]
if "--help" in args:
    print(
        control.get(
            "help",
            {
                "codex": "exec --model --sandbox --ephemeral --skip-git-repo-check "
                "--ignore-user-config --ignore-rules --output-schema --output-last-message "
                "--disable --config",
                "claude": "-p --model --output-format --json-schema --tools --no-session-persistence "
                "--strict-mcp-config --mcp-config --setting-sources --settings "
                "--safe-mode --disable-slash-commands --permission-mode",
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
