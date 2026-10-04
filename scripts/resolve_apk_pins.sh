#!/bin/sh
# Resolve exact apk versions for the worker's build toolchain and write
# apk.worker-build.lock (Gate 5: reproducible over time, not just back to back).
#
# WHY: `apk add gcc musl-dev` installs whatever the Alpine branch serves today,
# and the compiler version reaches the worker image's bytes (owlready2's C
# optimizer is compiled in the deps-builder stage and copied into the runtime).
# Pinning only the named packages is not enough: apk resolves their
# dependencies (binutils, gmp, ...) unversioned. This script asks apk, inside
# the digest-pinned base image, for the full install closure and pins every
# package in it.
#
# Alpine keeps only the newest build of each package on a branch, so a pinned
# version disappears when the branch ships an update. The build then fails
# loudly ("unable to select packages") instead of drifting silently. Refresh:
# bump the base digest (or not), re-run this script, rebuild, re-run Gate 5.
#
# Usage: scripts/resolve_apk_pins.sh   (needs docker and network)
set -eu

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DOCKERFILE="$REPO_ROOT/Dockerfile.worker"
OUT="$REPO_ROOT/apk.worker-build.lock"
PACKAGES="gcc musl-dev"

IMAGE=$(sed -n 's/^ARG RUNTIME_IMAGE=//p' "$DOCKERFILE")
[ -n "$IMAGE" ] || { echo "error: no ARG RUNTIME_IMAGE in $DOCKERFILE" >&2; exit 2; }

PINS=$(docker run --rm "$IMAGE" sh -c "apk add --simulate --no-cache $PACKAGES" \
    | sed -n 's/^([ 0-9]*\/[0-9]*) Installing \([^ ]*\) (\([^)]*\))$/\1=\2/p' \
    | sort)
[ -n "$PINS" ] || { echo "error: apk resolved no packages" >&2; exit 1; }

{
    echo "# Worker deps-builder toolchain: full apk install closure of: $PACKAGES"
    echo "# Resolved in $IMAGE"
    echo "# Regenerate with scripts/resolve_apk_pins.sh; never edit by hand."
    echo "$PINS"
} > "$OUT"
echo "wrote $OUT ($(echo "$PINS" | wc -l) packages)"
