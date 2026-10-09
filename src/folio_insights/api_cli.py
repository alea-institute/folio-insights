"""``folio-insights api``: API server administration (drain plan U5, R15, KTD10).

``folio-insights api token-new <handle> [--role operator] [--append FILE]`` mints an operator
token for the API's state-changing routes. The token is printed once and never stored; only its
SHA-256 goes in the tokens file named by ``FOLIO_INSIGHTS_API_TOKENS_FILE`` (see ``api/auth.py``
and "API authentication" in ``docs/storage-operations.md``).

Output contract: stdout carries exactly the token, then (without ``--append``) the tokens-file
line; guidance goes to stderr. So ``TOKEN=$(folio-insights api token-new alice --append FILE)``
captures only the token.
"""

from __future__ import annotations

import os
from pathlib import Path

import click


@click.group("api")
def api_group() -> None:
    """API server administration: operator tokens for state-changing routes."""


def _append_line(path: Path, line: str) -> None:
    """Append *line* to the tokens file at *path*, creating it with mode 600 if absent.

    An existing file must already pass the server's checks (private regular file owned by this
    user, every line valid); the result is re-validated after writing.
    """
    from api.auth import TokensFileError, check_file_security, load_tokens_file

    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        load_tokens_file(path)  # refuses an insecure or malformed existing file
        try:
            fd = os.open(path, flags)  # O_NOFOLLOW: never append through a symlink
        except OSError as exc:
            raise TokensFileError(f"{path}: cannot open for append ({exc.strerror})") from None
        created = False
    except OSError as exc:
        raise TokensFileError(f"{path}: cannot create ({exc.strerror})") from None
    try:
        if created:
            os.fchmod(fd, 0o600)
        check_file_security(os.fstat(fd), path)
        prefix = b""
        if not created and os.fstat(fd).st_size:
            with open(path, "rb") as existing:
                existing.seek(-1, os.SEEK_END)
                prefix = b"" if existing.read(1) == b"\n" else b"\n"
        os.write(fd, prefix + line.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    load_tokens_file(path)


@api_group.command("token-new")
@click.argument("handle")
@click.option("--role", default="operator", show_default=True,
              help="Role recorded for the token: operator or admin.")
@click.option("--append", "append_to", default=None,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Append the line to this tokens file (created with mode 600 if absent; an "
                   "existing file must already be private and valid).")
def token_new(handle: str, role: str, append_to: Path | None) -> None:
    """Mint an operator token for HANDLE and print it ONCE.

    Only the token's SHA-256 is ever stored. Without --append, also prints the line to add to
    the tokens file named by FOLIO_INSIGHTS_API_TOKENS_FILE.
    """
    from api.auth import AuthConfigError, entry_line, generate_token

    token = generate_token()
    try:
        line = entry_line(token, handle, role)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from None
    if append_to is not None:
        try:
            _append_line(append_to.expanduser(), line)
        except AuthConfigError as exc:
            raise click.ClickException(str(exc)) from None
    click.echo(
        f"Operator token for {handle} ({role}). It is shown once and stored nowhere; "
        "keep it in a password manager:", err=True,
    )
    click.echo(token)
    if append_to is None:
        click.echo(
            "Append this line (the token's hash, not the token) to the tokens file named by "
            "FOLIO_INSIGHTS_API_TOKENS_FILE (mode 600, outside the repository):", err=True,
        )
        click.echo(line)
    else:
        click.echo(f"Appended its hash to {append_to}.", err=True)
    click.echo("Send it as: Authorization: Bearer <token>", err=True)


__all__ = ["api_group"]
