"""Run governance script commands under an offline guard.

``python -m tests.proposals._offline [--script=NAME] <argv-json-list>...``: each
argument is a JSON list of CLI arguments for one ``main`` call of
``scripts/NAME.py`` (default ``judge_proposals``), run in order in this one
process. Before anything runs, the guard:

* makes every socket connect / DNS lookup raise and records the attempt;
* records (and refuses) any import of a model-client module: the folio-enrich
  LLM registry, the LLM bridge, and the common provider SDKs.

Prints one JSON line: each command's result, the refused imports and the
refused connection attempts.
"""
from __future__ import annotations

import importlib
import importlib.abc
import json
import socket
import sys
from pathlib import Path

WATCHED = (
    "app.services.llm",
    "folio_insights.services.bridge.llm_bridge",
    "anthropic",
    "openai",
    "google.genai",
    "google.generativeai",
    "litellm",
    "httpx",
    "requests",
)
refused_imports: list[str] = []
refused_connections: list[str] = []


class _RefuseModelClients(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if any(fullname == w or fullname.startswith(w + ".") for w in WATCHED):
            refused_imports.append(fullname)
            raise ImportError(f"offline guard: import of {fullname} refused")
        return None


def _refuse(name):
    def _raise(*args, **kwargs):  # noqa: ARG001
        refused_connections.append(name)
        raise OSError(f"offline guard: {name} refused")
    return _raise


def main(argv: list[str]) -> None:
    already = sorted(m for m in sys.modules if any(m == w or m.startswith(w + ".") for w in WATCHED))
    sys.meta_path.insert(0, _RefuseModelClients())
    socket.socket.connect = _refuse("socket.connect")
    socket.socket.connect_ex = _refuse("socket.connect_ex")
    socket.create_connection = _refuse("socket.create_connection")
    socket.getaddrinfo = _refuse("socket.getaddrinfo")

    script = "judge_proposals"
    if argv and argv[0].startswith("--script="):
        script = argv[0].split("=", 1)[1]
        argv = argv[1:]
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts"))
    module = importlib.import_module(script)

    results = []
    for raw in argv:
        results.append(module.main(json.loads(raw)))
    print(json.dumps({
        "exit_codes": results,
        "preloaded": already,
        "refused_imports": refused_imports,
        "refused_connections": refused_connections,
    }))


if __name__ == "__main__":
    main(sys.argv[1:])
