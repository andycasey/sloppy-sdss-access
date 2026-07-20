"""Credentials for collaboration-access SDSS data.

Public data releases need no authentication. Everything else -- ``sdsswork``,
the IPLs, and any DR whose release date has not yet passed -- sits behind HTTP
Basic auth on the SAS.

Credentials are resolved from the first source that supplies them
(sdss/sdss_access#95, "dynamic / in-python user authentication"):

1. passed explicitly in code                 -- scripts, notebooks, tests
2. ``$SDSS_USER`` / ``$SDSS_PASSWORD``       -- CI, containers
3. ``~/.netrc`` keyed by host                -- the existing sdss_access setup
4. an interactive prompt                     -- opt-in, and never in a non-TTY

Unlike ``sdss_access.sync.auth``, nothing here prompts implicitly. A library
that blocks on ``input()`` in the middle of a batch job is a bug, so prompting
must be asked for with ``allow_prompt=True`` and is skipped anyway when stdin is
not a terminal.
"""

from __future__ import annotations

import base64
import datetime
import netrc
import os
import stat
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Credentials", "resolve", "is_public", "AuthError"]


class AuthError(Exception):
    """No usable credentials could be found."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """A username/password pair for the SAS.

    The password is kept out of ``repr`` so it cannot leak into logs,
    tracebacks, or notebook output.
    """

    username: str
    password: str = field(repr=False)

    def as_header(self) -> str:
        """An HTTP Basic ``Authorization`` header value."""
        token = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode("ascii")
        return f"Basic {token}"

    def as_storage_options(self) -> dict:
        """fsspec ``storage_options`` carrying these credentials.

        Sent as an explicit Authorization header rather than
        ``aiohttp.BasicAuth``, which is deprecated in aiohttp 4.
        """
        return {"client_kwargs": {"headers": {"Authorization": self.as_header()}}}

    def __str__(self) -> str:
        return f"Credentials(username={self.username!r}, password=<hidden>)"


def is_public(release: str, release_date: str | None, today: datetime.date | None = None) -> bool:
    """Is this release publicly readable *yet*?

    A DR is public only once its release date has actually passed -- DR20 is
    dated 2026-07-30, so before then it still needs collaboration credentials.
    ``sdsswork`` and the IPLs are never public.
    """
    if not release.lower().startswith("dr"):
        return False
    if not release_date:
        return False
    today = today or datetime.date.today()
    try:
        return datetime.date.fromisoformat(release_date) <= today
    except ValueError:
        return False


def _from_env() -> Credentials | None:
    user = os.environ.get("SDSS_USER")
    password = os.environ.get("SDSS_PASSWORD")
    if user and password:
        return Credentials(user, password)
    return None


def _from_netrc(host: str, path: Path | None = None) -> Credentials | None:
    """Read credentials for ``host`` from a netrc file, if one exists."""
    if path is None:
        # Windows conventionally uses _netrc; netrc.netrc() finds ~/.netrc itself.
        candidates = [Path.home() / ".netrc", Path.home() / "_netrc"]
        path = next((p for p in candidates if p.exists()), None)
    if path is None or not path.exists():
        return None

    _warn_if_world_readable(path)

    try:
        auth = netrc.netrc(str(path)).authenticators(host)
    except (netrc.NetrcParseError, OSError) as exc:
        warnings.warn(f"could not parse {path}: {exc}", stacklevel=2)
        return None

    if not auth:
        return None
    login, _account, password = auth
    if login and password:
        return Credentials(login, password)
    return None


def _warn_if_world_readable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        warnings.warn(
            f"{path} is readable by other users; run `chmod 600 {path}`",
            stacklevel=3,
        )


def _from_prompt(host: str) -> Credentials | None:
    """Prompt interactively. Returns None when there is no terminal to prompt on."""
    if not sys.stdin.isatty():
        return None
    from getpass import getpass

    print(f"SDSS credentials for {host}", file=sys.stderr)
    username = input("  username: ").strip()
    if not username:
        return None
    password = getpass("  password: ")
    if not password:
        return None
    return Credentials(username, password)


def resolve(
    host: str,
    *,
    username: str | None = None,
    password: str | None = None,
    netrc_path: Path | str | None = None,
    allow_prompt: bool = False,
    required: bool = True,
) -> Credentials | None:
    """Find credentials for ``host``, trying each source in turn.

    Parameters
    ----------
    host
        Netrc machine name, e.g. ``data.sdss5.org``.
    username, password
        Supplied explicitly; short-circuits every other source.
    netrc_path
        Override the netrc file location.
    allow_prompt
        Permit an interactive prompt as a last resort. Ignored without a TTY.
    required
        Raise :class:`AuthError` when nothing is found, rather than returning None.
    """
    if username and password:
        return Credentials(username, password)

    found = _from_env()
    if found is None:
        found = _from_netrc(host, Path(netrc_path) if netrc_path else None)
    if found is None and allow_prompt:
        found = _from_prompt(host)

    if found is None and required:
        raise AuthError(
            f"No SDSS credentials for {host!r}. Provide them by any of:\n"
            f"  - Access(..., username=..., password=...)\n"
            f"  - export SDSS_USER=... SDSS_PASSWORD=...\n"
            f"  - a ~/.netrc entry:\n"
            f"        machine {host}\n"
            f"        login <user>\n"
            f"        password <password>\n"
            f"    (then chmod 600 ~/.netrc)\n"
            f"  - Access(..., allow_prompt=True) to be asked interactively"
        )
    return found
