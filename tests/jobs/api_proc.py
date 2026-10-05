"""Child-process API for the restart tests: the real app, lifespan and embedded worker.

``python -m tests.jobs.api_proc submit --output DIR --corpus NAME [--provider P] [--key-env VAR]``
    creates the corpus, POSTs /process (with the key from env var VAR, if given) and keeps
    serving -- the embedded worker runs the job -- until the test kills the process.

``python -m tests.jobs.api_proc resume --output DIR --corpus NAME [--key-env VAR]``
    a restarted API: serves with its embedded worker, optionally re-supplies the key through
    POST /job/credentials, and exits once the job settles, printing the final job JSON.

The key is read from an environment variable named on the command line, never passed as an
argument (argv is visible in process listings).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import tests.jobs.fake_pipeline  # noqa: F401 - patches the orchestrator stages + LLM transport


async def _main(args: argparse.Namespace) -> None:
    import httpx

    from api import main as api_main
    from api.main import app

    api_main.configure(output_dir=Path(args.output))
    key = os.environ.get(args.key_env) if args.key_env else None
    headers = {"X-LLM-API-Key": key} if key else {}
    async with app.router.lifespan_context(app):  # starts the embedded worker
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            if args.mode == "submit":
                created = await client.post("/api/v1/corpora", json={"name": args.corpus})
                resp = await client.post(f"/api/v1/corpus/{args.corpus}/process",
                                         json={"llm_provider": args.provider}, headers=headers)
                print(json.dumps({"corpus": created.status_code, "submit": resp.status_code,
                                  "body": resp.json()}), flush=True)
                await asyncio.Event().wait()  # serve until killed
            else:
                if key:
                    # The job parks as needs_credentials once this process's worker reclaims
                    # the dead process's expired lease; re-supply as soon as it does.
                    for _ in range(600):
                        resp = await client.post(f"/api/v1/corpus/{args.corpus}/job/credentials",
                                                 headers=headers)
                        if resp.status_code == 200:
                            break
                        await asyncio.sleep(0.05)
                    print(json.dumps({"resupply": resp.status_code}), flush=True)
                for _ in range(600):
                    job = (await client.get(f"/api/v1/corpus/{args.corpus}/job")).json()
                    if job["status"] in {"completed", "failed", "cancelled"} or (
                        job["status"] == "needs_credentials" and not key
                    ):
                        break
                    await asyncio.sleep(0.05)
                print(json.dumps({"final": job}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["submit", "resume"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--key-env", default=None)
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
