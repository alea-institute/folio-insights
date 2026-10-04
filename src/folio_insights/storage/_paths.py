"""Filesystem boundaries shared by exports, dumps, snapshots and restores.

* ``served_output_dirs`` — every location the served ``output/`` directory
  can be: the configured ``output_dir`` resolved against the current
  directory (how the API resolves it) and against the project root. If the
  settings cannot be loaded the guard fails CLOSED (``StorageError``)
  instead of switching itself off.
* ``rename_noreplace`` — rename that never replaces an existing destination
  (``renameat2(RENAME_NOREPLACE)`` on Linux; elsewhere a check-then-rename
  that refuses an existing destination).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
from pathlib import Path

from folio_insights.storage.errors import StorageError

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def served_output_dirs() -> tuple[Path, ...]:
    """Resolved candidate locations of the served output directory."""
    try:
        from folio_insights.config import get_settings

        configured = Path(get_settings().output_dir).expanduser()
    except Exception as exc:  # noqa: BLE001 - any failure means "cannot tell"
        raise StorageError(
            f"cannot determine the served output directory ({type(exc).__name__}); "
            "refusing to write storage artifacts until settings load"
        ) from None
    if configured.is_absolute():
        return (configured.resolve(),)
    return tuple(
        dict.fromkeys(
            (
                (Path.cwd() / configured).resolve(),
                (_PROJECT_ROOT / configured).resolve(),
            )
        )
    )


def inside(path: Path, other: Path) -> bool:
    path, other = Path(path).resolve(), Path(other).resolve()
    return path == other or other in path.parents


def inside_served_output(path: Path) -> Path | None:
    """The served directory ``path`` is inside (or equal to), else ``None``."""
    for served in served_output_dirs():
        if inside(path, served):
            return served
    return None


_RENAME_NOREPLACE = 1
_AT_FDCWD = -100
_renameat2 = None
try:  # pragma: no branch - platform-specific
    _libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    _renameat2 = _libc.renameat2
    _renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                           ctypes.c_uint]
    _renameat2.restype = ctypes.c_int
except (OSError, AttributeError):  # pragma: no cover - non-glibc platforms
    _renameat2 = None


def rename_noreplace(src: Path, dst: Path) -> None:
    """Rename ``src`` to ``dst``; raise ``FileExistsError`` if ``dst`` exists."""
    if _renameat2 is not None:
        rc = _renameat2(_AT_FDCWD, os.fsencode(src), _AT_FDCWD, os.fsencode(dst),
                        _RENAME_NOREPLACE)
        if rc == 0:
            return
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise FileExistsError(errno.EEXIST, "destination exists", str(dst))
        if err not in (errno.ENOSYS, errno.EINVAL):
            raise OSError(err, os.strerror(err), str(dst))
    # Fallback (no renameat2 / unsupported filesystem): refuse an existing
    # destination; the remaining window is the gap between check and rename.
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "destination exists", str(dst))
    os.rename(src, dst)


__all__ = ["inside", "inside_served_output", "rename_noreplace", "served_output_dirs"]
