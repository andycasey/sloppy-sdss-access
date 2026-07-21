"""Drop-in shims for the legacy ``sdss_access`` API.

``sloppy-sdss-access`` re-exports the legacy ``sdss_access`` names (``Path``,
``SDSSPath``, ``RsyncAccess``, ...) from ``sloppy_sdss_access``, so porting is a
one-line import change (``from sdss_access import Path`` becomes
``from sloppy_sdss_access import Path``). This module makes that code keep
*working* where the semantics allow.

It is a compatibility layer, not an emulator. Read the differences below before
relying on it.

**What maps cleanly**

============================  ====================================
legacy                        here
============================  ====================================
``Path(release=...)``         :class:`Path` -> wraps :class:`~sloppy_sdss_access.paths.SDSS`
``.full(species, **keys)``    absolute path under the SAS root
``.url(species, **keys)``     identical
``.location(species, ...)``   SAS-relative path (our native ``.path()``)
``.exists(species, ...)``     local filesystem check
``AccessError``               :class:`AccessError`
============================  ====================================

**What deliberately differs**

* ``.full()`` needs a SAS root. Legacy took it from ``$SAS_BASE_DIR``, which it
  also *wrote*. Here it is read-only, and falls back to ``~/sas``. If you only
  want the archive-relative path, use ``.location()`` -- or better, the native
  ``SDSS.path()``.
* Missing keys raise :class:`~sloppy_sdss_access.paths.MissingKeys` instead of
  returning a malformed path with an empty segment in it.
* Products whose tree template references an undefined variable raise
  :class:`~sloppy_sdss_access.paths.UnresolvableProduct` instead of returning a path
  containing a literal ``$VAR``.
* Nothing touches ``os.environ``. Legacy replanted the tree on every ``Path()``
  construction, overwriting ~97 variables; that is why two releases interfered.
* DR7-DR12 are not available. ``Path(release="dr12")`` raises.

**What is NOT provided**

``RsyncAccess`` and ``CurlAccess`` have no equivalent -- downloads go over
HTTPS via fsspec rather than rsync or curl, and the ``add()``/``set_stream()``/``commit()`` batching
model does not map onto :class:`~sloppy_sdss_access.access.Access`. Importing them
raises with a pointer to the replacement. ``HttpAccess`` and ``Access`` are
provided as thin adapters over the fsspec backend.
"""

from __future__ import annotations

import os
from pathlib import Path as _Path
from typing import Any

from .access import Access as _Access
from .paths import SDSS, MissingKeys, UnknownProduct, UnresolvableProduct

__all__ = [
    "Path",
    "SDSSPath",
    "AccessError",
    "HttpAccess",
    "Access",
    "RsyncAccess",
    "CurlAccess",
]


class AccessError(Exception):
    """Legacy error type. Retained so ``except AccessError`` keeps compiling."""


class Path:
    """Legacy-shaped wrapper around :class:`~sloppy_sdss_access.paths.SDSS`.

    ::

        from sloppy_sdss_access import Path

        p = Path(release="dr19")
        p.full("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)

    ``verbose``, ``public``, ``force_modules`` and ``preserve_envvars`` are
    accepted and ignored: this package has no global environment to preserve,
    and access is decided by HTTP auth rather than by URL.
    """

    def __init__(
        self,
        release: str | None = None,
        public: bool = False,
        mirror: bool = False,
        verbose: bool = False,
        force_modules: bool | None = None,
        preserve_envvars: bool | list | None = None,
        root: str | os.PathLike | None = None,
    ) -> None:
        del public, verbose, force_modules, preserve_envvars  # no longer meaningful
        self.release = (release or "dr19").lower().replace("-", "")
        self._paths = SDSS(release=self.release, root=root, mirror=mirror)
        # Legacy validated the release when the Path was constructed. SDSS
        # loads lazily, so touch the registry here to fail at the same point.
        self._paths._release

    # -- the four methods most legacy code actually calls -----------------

    def full(self, filetype: str, **kwargs: Any) -> str:
        """Absolute local path, as legacy returned.

        Requires a SAS root: ``root=`` on construction, else ``$SAS_BASE_DIR``,
        else ``~/sas``. Prefer :meth:`location` if you want the relative path.
        """
        if "full" in kwargs:
            return kwargs["full"]
        return str(self._paths.local(filetype, **self._clean(kwargs)))

    def location(self, filetype: str, **kwargs: Any) -> str:
        """SAS-relative path -- this package's native answer."""
        return self._paths.path(filetype, **self._clean(kwargs))

    def url(self, filetype: str, **kwargs: Any) -> str:
        """Public URL on the SAS."""
        return self._paths.url(filetype, **self._clean(kwargs))

    def exists(self, filetype: str, **kwargs: Any) -> bool:
        """Does the file exist locally? (Legacy also had a ``remote`` flag.)"""
        if kwargs.get("remote"):
            return _Access(self._paths).exists(filetype, **self._clean(kwargs))
        return _Path(self.full(filetype, **kwargs)).exists()

    def name(self, filetype: str, **kwargs: Any) -> str:
        """Filename only."""
        return self.location(filetype, **kwargs).rsplit("/", 1)[-1]

    def dir(self, filetype: str, **kwargs: Any) -> str:
        """Directory containing the product."""
        return str(_Path(self.full(filetype, **kwargs)).parent)

    # -- introspection ----------------------------------------------------

    @property
    def templates(self) -> dict[str, str]:
        """``{species: template}``, as legacy exposed."""
        return {
            species: product.template
            for species, product in self._paths._release.products.items()
        }

    def lookup_keys(self, filetype: str) -> list[str]:
        return list(self._paths.keys(filetype))

    def lookup_names(self) -> list[str]:
        return sorted(self._paths)

    def has_name(self, filetype: str) -> bool:
        return filetype in self._paths

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _clean(kwargs: dict[str, Any]) -> dict[str, Any]:
        """Drop legacy-only control kwargs that are not path keys."""
        return {
            k: v
            for k, v in kwargs.items()
            if k not in ("force_module", "skip_tag_check", "remote", "full")
        }

    def __repr__(self) -> str:
        return f"Path(release={self.release!r}, compat=True)"


#: Legacy alias.
SDSSPath = Path


class HttpAccess:
    """Minimal stand-in for the legacy HTTP downloader.

    Legacy usage ``HttpAccess(release=...).get(species, **keys)`` maps onto
    :meth:`~sloppy_sdss_access.access.Access.fetch`.
    """

    def __init__(self, release: str | None = None, verbose: bool = False, **kwargs: Any):
        del verbose, kwargs
        self.release = (release or "dr19").lower().replace("-", "")
        self._access = _Access(SDSS(self.release))

    def set_auth(self, username: str | None = None, password: str | None = None, **kwargs: Any):
        """Legacy auth entry point. Prefers explicit credentials, else netrc/env."""
        del kwargs
        self._access.username = username
        self._access.password = password

    def get(self, filetype: str, **kwargs: Any) -> str:
        return str(self._access.fetch(filetype, **Path._clean(kwargs)))

    def exists(self, filetype: str, **kwargs: Any) -> bool:
        return self._access.exists(filetype, **Path._clean(kwargs))


#: ``Access`` was the posix/windows-dispatching downloader. Point it at the
#: fsspec-backed replacement rather than pretending rsync exists.
Access = _Access


def _unsupported(name: str, why: str):
    def _raise(*_args: Any, **_kwargs: Any):
        raise NotImplementedError(
            f"{name} is not provided by sloppy-sdss-access. {why}\n"
            "Use:  from sloppy_sdss_access import SDSS, Access\n"
            "      a = Access(SDSS('dr19'))\n"
            "      a.fetch(species, **keys)                 # one file\n"
            "      a.fetch_many([(species, keys), ...])     # concurrent\n"
            "      a.open(species, **keys)                  # stream, no download"
        )

    return _raise


RsyncAccess = _unsupported(
    "RsyncAccess",
    "There is no rsync transport; downloads go over HTTPS via fsspec, and the "
    "add()/set_stream()/commit() batching model is replaced by fetch_many().",
)
CurlAccess = _unsupported(
    "CurlAccess",
    "There is no curl transport; downloads go over HTTPS via fsspec.",
)
