"""Remote access to SDSS-5 data products, via ``fsspec``.

One backend covers every transport SDSS cares about:

* ``https`` -- the SAS (default)
* ``s3``    -- e.g. the MAST public bucket (sdss/sdss_access#101)
* ``file``  -- a local SAS mount, no download at all

and gives three things the legacy rsync/curl stack cannot:

* **Streaming.** :meth:`Access.open` returns a file object backed by HTTP range
  requests, so ``astropy.io.fits.open`` reads a header without pulling the file
  (sdss/sdss_access#96).
* **Async.** :meth:`Access.fetch_many` downloads concurrently, and
  :meth:`Access.afetch_many` is awaitable for callers already in an event loop
  (sdss/sdss_access#99).
* **Caching.** Fetches are content-cached on disk, so a repeat call is free
  and there is no "did I already rsync this?" bookkeeping.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import fsspec

from .auth import Credentials, resolve
from .paths import MIRROR_HOST, SAS_HOST, SDSS
from .registry import load

__all__ = ["Access"]

DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")) / "sloppy_sdss_access"

# Suffixes the SAS uses that a tree template may or may not mention.
COMPRESSION_SUFFIXES = (".gz", ".bz2", ".fz", ".zip", ".Z")


@dataclass(slots=True)
class Access:
    """Fetch SDSS-5 products over any fsspec-supported transport.

    Parameters
    ----------
    paths
        An :class:`~sloppy_sdss_access.paths.SDSS` release object.
    protocol
        ``https`` (default), ``s3``, or ``file``.
    cache
        Directory for the local content cache. ``None`` disables caching.
    bucket
        For ``protocol="s3"``, the bucket holding the SAS tree.
    storage_options
        Passed through to the fsspec filesystem (credentials, headers, ...).
    """

    paths: SDSS
    protocol: str = "https"
    cache: Path | str | None = DEFAULT_CACHE
    bucket: str | None = None
    storage_options: dict[str, Any] = field(default_factory=dict)

    # Authentication. Only consulted for releases that are not yet public.
    username: str | None = None
    password: str | None = None
    netrc_path: Path | str | None = None
    allow_prompt: bool = False

    # Probe for compressed/uncompressed variants when the template is wrong.
    probe_compression: bool = True

    _credentials: Credentials | None = field(default=None, init=False, repr=False)
    #: species -> suffix correction learned by probing (e.g. {"mwmStar": ""}).
    _suffix_fix: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    # ------------------------------------------------------------------
    # authentication
    # ------------------------------------------------------------------

    @property
    def host(self) -> str:
        """The netrc machine name for this release's data host."""
        return (MIRROR_HOST if self.paths.mirror else SAS_HOST).split("//", 1)[1].split("/", 1)[0]

    @property
    def is_public(self) -> bool:
        """True when this release needs no credentials."""
        return load(self.paths.release).is_public

    @property
    def credentials(self) -> Credentials | None:
        """Credentials for this release, resolved once and cached.

        Returns ``None`` for public releases, which need none.
        """
        if self.is_public or self.protocol == "file":
            return None
        if self._credentials is None:
            self._credentials = resolve(
                self.host,
                username=self.username,
                password=self.password,
                netrc_path=self.netrc_path,
                allow_prompt=self.allow_prompt,
                required=True,
            )
        return self._credentials

    @property
    def _options(self) -> dict[str, Any]:
        """Storage options with credentials folded in, for http backends."""
        opts = dict(self.storage_options)
        creds = self.credentials
        if creds is not None and self.protocol in ("http", "https"):
            client_kwargs = dict(opts.get("client_kwargs", {}))
            headers = dict(client_kwargs.get("headers", {}))
            headers.setdefault("Authorization", creds.as_header())
            client_kwargs["headers"] = headers
            opts["client_kwargs"] = client_kwargs
        return opts

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------

    def uri(self, species: str, **keys: Any) -> str:
        """The transport-specific URI for a product, exactly as templated."""
        relative = self.paths.path(species, **keys)
        if self.protocol == "s3":
            if not self.bucket:
                raise ValueError("protocol='s3' requires a bucket")
            return f"s3://{self.bucket}/{relative}"
        if self.protocol == "file":
            return str(self.paths.local(species, **keys))
        return self.paths.url(species, **keys)

    def _variants(self, uri: str) -> list[str]:
        """The URI as templated, then each compression suffix appended.

        Only reached for products the registry marks ``may_be_compressed``,
        which by construction do not already carry a suffix.
        """
        return [uri, *(uri + suffix for suffix in COMPRESSION_SUFFIXES)]

    def resolve_uri(self, species: str, **keys: Any) -> str:
        """The URI of the product *as it actually exists on the server*.

        Tree templates and the SAS disagree about compression more often than
        you would hope -- ``sdsswork``'s ``astraAllStarASPCAP`` is templated
        ``.fits`` but stored ``.fits.gz`` (DR19's template has it right). This
        returns whichever variant is really there (sdss/sdss_access#66).

        Two things keep that cheap:

        * **The registry says whether a probe is even possible.** A template
          that already names ``.gz``, or whose extension is never compressed
          (``.png``, ``.parquet``, ``.h5``), is returned untouched with no
          request at all. Only ``product.may_be_compressed`` products probe.
        * **The correction is learned once per species, not per file.** The SAS
          does not compress one ``mwmStar`` and not the next, so the suffix
          discovered for the first is reused for the rest. Looping over 10,000
          stars costs one extra HEAD, not 10,000.

        ``sdss_access`` does this by ``stat``-ing the *local* filesystem, so it
        only self-corrects on a machine with a SAS mount; this works remotely.
        Set ``probe_compression=False`` to skip probing entirely.
        """
        exact = self.uri(species, **keys)
        if not self.probe_compression or self.protocol == "file":
            return exact

        # Does this product admit a compression variant at all?
        product = self.paths.product(species)
        if not product.may_be_compressed:
            return exact

        # Already learned the correction for this species?
        if species in self._suffix_fix:
            return exact + self._suffix_fix[species]

        fs = self.fs
        for candidate in self._variants(exact):
            try:
                if fs.exists(candidate):
                    self._suffix_fix[species] = candidate[len(exact) :]
                    return candidate
            except Exception:  # noqa: BLE001 -- a failed probe is not fatal
                continue

        # Nothing found; don't cache a guess, so a later call can retry.
        return exact

    @property
    def fs(self):
        """The underlying fsspec filesystem (uncached)."""
        return fsspec.filesystem(self.protocol, **self._options)

    # ------------------------------------------------------------------
    # single-file operations
    # ------------------------------------------------------------------

    def exists(self, species: str, **keys: Any) -> bool:
        """Does the product exist remotely? No download."""
        return self.fs.exists(self.resolve_uri(species, **keys))

    def size(self, species: str, **keys: Any) -> int:
        """Product size in bytes, from a HEAD request."""
        return self.fs.size(self.resolve_uri(species, **keys))

    def open(self, species: str, mode: str = "rb", block_cache: bool = False, **keys: Any):
        """Open a product as a file object *without* downloading it.

        Backed by HTTP range requests, so this reads a FITS header, or a single
        Parquet row-group, without transferring the whole file::

            with access.open("astraAllStar", ...) as fp:
                header = fits.open(fp)[0].header

        Note this deliberately bypasses the whole-file cache used by
        :meth:`fetch` -- ``filecache`` would download the entire file up front,
        which is exactly what streaming is meant to avoid. Pass
        ``block_cache=True`` to cache the byte ranges actually read, which is
        worth it for repeated random access to one large file.
        """
        uri = self.resolve_uri(species, **keys)
        if block_cache and self.protocol != "file":
            return fsspec.open(
                f"blockcache::{uri}",
                mode=mode,
                blockcache={"cache_storage": str(Path(self.cache or DEFAULT_CACHE).expanduser())},
                **{self.protocol: self._options},
            ).open()
        return self.fs.open(uri, mode)

    def fetch(self, species: str, **keys: Any) -> Path:
        """Download one product to the cache and return its local path."""
        uri = self.resolve_uri(species, **keys)
        if self.protocol == "file":
            return Path(uri)

        target = self._target(uri)
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        self.fs.get_file(uri, str(target))
        return target

    def _target(self, uri: str) -> Path:
        """Mirror the SAS layout inside the cache, so files stay identifiable."""
        base = Path(self.cache or DEFAULT_CACHE).expanduser()
        relative = uri.split("/sas/", 1)[-1] if "/sas/" in uri else uri.split("://")[-1]
        return base / relative

    # ------------------------------------------------------------------
    # concurrent operations
    # ------------------------------------------------------------------

    def fetch_many(
        self,
        items: Sequence[tuple[str, dict[str, Any]]],
        concurrency: int = 8,
        skip_missing: bool = False,
    ) -> list[Path | None]:
        """Download many products concurrently. Blocking.

        ``items`` is a sequence of ``(species, keys)`` pairs::

            access.fetch_many([
                ("astraStar", {"cat_id": 1, ...}),
                ("astraStar", {"cat_id": 2, ...}),
            ])

        Raises :class:`RuntimeError` if called from inside a running event loop
        (a notebook, say) -- use :meth:`afetch_many` there instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "fetch_many() cannot run inside an active event loop "
                "(e.g. Jupyter). Use `await access.afetch_many(...)` instead."
            )
        return asyncio.run(
            self.afetch_many(items, concurrency=concurrency, skip_missing=skip_missing)
        )

    async def afetch_many(
        self,
        items: Sequence[tuple[str, dict[str, Any]]],
        concurrency: int = 8,
        skip_missing: bool = False,
    ) -> list[Path | None]:
        """Await many downloads concurrently.

        Use this when you are already inside an event loop; use
        :meth:`fetch_many` otherwise.

        With ``skip_missing=True`` a file that cannot be fetched yields ``None``
        in its slot instead of aborting the batch (sdss/sdss_access#89). The
        returned list is always positionally aligned with ``items``.
        """
        uris = [self.resolve_uri(species, **keys) for species, keys in items]
        targets = [self._target(u) for u in uris]

        if self.protocol == "file":
            return [Path(u) for u in uris]

        fs = fsspec.filesystem(self.protocol, asynchronous=True, **self._options)
        semaphore = asyncio.Semaphore(concurrency)

        async def one(uri: str, target: Path) -> Path:
            if target.exists():
                return target
            async with semaphore:
                target.parent.mkdir(parents=True, exist_ok=True)
                await fs._get_file(uri, str(target))
            return target

        try:
            results = await asyncio.gather(
                *(one(u, t) for u, t in zip(uris, targets)),
                return_exceptions=True,
            )
        finally:
            session = getattr(fs, "_session", None)
            if session is not None:
                await session.close()

        out: list[Path | None] = []
        for (species, _keys), result in zip(items, results):
            if isinstance(result, BaseException):
                if not skip_missing:
                    raise result
                out.append(None)
            else:
                out.append(result)
        return out

    # ------------------------------------------------------------------

    def glob(self, species: str, **keys: Any) -> list[str]:
        """Expand a product whose keys contain ``*`` wildcards."""
        return self.fs.glob(self.uri(species, **keys))

    def __repr__(self) -> str:
        return (
            f"Access(release={self.paths.release!r}, protocol={self.protocol!r}, "
            f"cache={'on' if self.cache else 'off'})"
        )
