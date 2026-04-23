"""Railway deploy wrapper — invoked by ci/build.py after successful publish.

D-10: deploy stage. Uses Railway CLI via subprocess (simpler than the
Railway GraphQL token dance). Requires ``RAILWAY_TOKEN`` env var.

Not wired into the Gate 5 determinism test directly (Gate 5 uses local Dagger
builds); Railway comparison is Mode 2 of ``tests/bench/test_gate5_digest.py``
and pulls the deployed image back for digest-equality assertion.

Threat note (T-00-19): ``RAILWAY_TOKEN`` is passed to the subprocess only via
``env=`` (never on argv), and this module does not log the token. CI runner
must set it as a masked secret.
"""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def deploy_service(service_name: str, *, image: str | None = None) -> None:
    """Trigger Railway deploy for one service.

    Args:
        service_name: ``"web"`` or ``"worker"`` — must match ``railway.toml``
            service names.
        image: Optional pre-built image ref (registry URL). If ``None``,
            Railway rebuilds from source using its own builder.

    Raises:
        RuntimeError: if ``RAILWAY_TOKEN`` is unset or the deploy fails.
    """
    token = os.environ.get("RAILWAY_TOKEN")
    if not token:
        raise RuntimeError("RAILWAY_TOKEN not set — cannot deploy")

    cmd = ["railway", "up", "--service", service_name, "--ci"]
    if image:
        # Railway's image-deploy path — syntax per railway-cli >= 3.x.
        # If this invocation fails on the actual Railway CLI version in use,
        # the fallback per Plan 05 Open Questions is `railway deploy` with
        # the image ref. Plan 07 exercises this path end-to-end.
        cmd.extend(["--image", image])

    logger.info("Deploying %s -> %s", service_name, image or "<Railway-rebuild>")

    # Pass token via env= only — never on argv (T-00-19 mitigation).
    result = subprocess.run(
        cmd,
        env={**os.environ, "RAILWAY_TOKEN": token},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Log stderr but NOT stdout (stdout may echo the image ref which is fine;
        # stderr is where railway-cli surfaces errors). Token itself never appears
        # in subprocess output because it is in env, not cmdline.
        logger.error("Railway deploy failed: %s", result.stderr)
        raise RuntimeError(
            f"railway up failed for {service_name}: {result.stderr.strip()}"
        )
    logger.info("Deployed %s", service_name)


if __name__ == "__main__":
    # Allow: `python -m ci.railway <service>` for manual re-deploys.
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m ci.railway <web|worker> [image_ref]", file=sys.stderr)
        sys.exit(2)
    service = sys.argv[1]
    img = sys.argv[2] if len(sys.argv) > 2 else None
    deploy_service(service, image=img)
