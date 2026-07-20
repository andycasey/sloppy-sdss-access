"""Path resolution for SDSS data products.

The whole surface is one immutable object::

    from sloppy_sdss_access import SDSS

    dr19 = SDSS("dr19")
    dr19.path("astraAllStar", component="", ...)   # -> SAS-relative path
    dr19.url("astraAllStar", ...)                  # -> https://data.sdss5.org/sas/...
    dr19.local("astraAllStar", ...)                # -> /your/sas/root/...

Because a release carries its own registry and nothing is stored in
``os.environ``, two releases coexist happily in one process -- which is the bug
reported in sdss/sdss_access#34 and the feature asked for in #97.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path as _Path
from typing import Any, Iterator

from .derive import DERIVATIONS
from .registry import Product, Release, load, releases

__all__ = ["SDSS", "UnknownProduct", "MissingKeys", "UnresolvableProduct"]

SPECIAL_RE = re.compile(r"@(\w+)\|")

# Remote roots. Public data releases are served from data.sdss.org; SDSS-5
# collaboration data (sdsswork, the IPLs, and DRs whose release date has not
# passed) from data.sdss5.org. This matches what sdss_access does, so the
# compat shim's url() agrees with the legacy one. Both hosts answer for most
# paths in practice, but matching the documented host avoids surprises.
PUBLIC_HOST = "https://data.sdss.org/sas"
COLLAB_HOST = "https://data.sdss5.org/sas"
MIRROR_HOST = "https://dev-mirror.sdss.org/sas"

#: Host used for authenticated (collaboration) access -- see sloppy_sdss_access.auth.
SAS_HOST = COLLAB_HOST


class UnknownProduct(KeyError):
    """No such product species in this release."""


class MissingKeys(KeyError):
    """Required keys were not supplied."""


class UnresolvableProduct(ValueError):
    """The template references an environment variable this release never defines."""


@dataclass(frozen=True, slots=True)
class SDSS:
    """Path resolution for one SDSS release.

    Parameters
    ----------
    release
        One of ``sdsswork``, ``ipl1``-``ipl4``, ``dr13``-``dr20``.
    root
        Local SAS root. Only needed for :meth:`local`. Defaults to ``~/sas``.
    mirror
        Resolve URLs against the mirror host instead of the primary.
    """

    release: str = "dr19"
    root: _Path | str | None = None
    mirror: bool = False

    # ------------------------------------------------------------------
    # registry access
    # ------------------------------------------------------------------

    @property
    def _release(self) -> Release:
        return load(self.release)

    @property
    def defaults(self) -> dict[str, str]:
        """Pipeline versions implied by this release (see registry.RELEASE_DEFAULTS)."""
        return dict(self._release.defaults)

    def __contains__(self, species: str) -> bool:
        return species in self._release

    def __len__(self) -> int:
        return len(self._release)

    def __iter__(self) -> Iterator[str]:
        return iter(self._release)

    def product(self, species: str) -> Product:
        """Look up one product definition."""
        try:
            return self._release.products[species]
        except KeyError:
            hint = self.search(f"*{species}*")[:5]
            suffix = f" Did you mean: {', '.join(hint)}?" if hint else ""
            raise UnknownProduct(
                f"{species!r} is not in release {self.release!r}.{suffix}"
            ) from None

    def search(self, pattern: str) -> list[str]:
        """Glob product names, case-insensitively."""
        low = pattern.lower()
        return sorted(
            s for s in self._release.products if fnmatch.fnmatch(s.lower(), low)
        )

    def keys(self, species: str) -> tuple[str, ...]:
        """Every key this product accepts, required and optional."""
        return self.product(species).keys

    def describe(self, species: str) -> str:
        return self.product(species).describe()

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    def path(self, species: str, **keys: Any) -> str:
        """Resolve a product to a SAS-root-relative path.

        Release defaults are filled in first, so on DR19 you may omit
        ``run2d``/``apred``/``v_astra``.
        """
        product = self.product(species)

        if product.broken:
            raise UnresolvableProduct(
                f"{species!r} in {self.release!r} references "
                f"{', '.join('$' + v for v in product.broken)}, which this release "
                "never defines. This is a defect in the upstream tree config; "
                "sdss_access silently returns a path with the literal variable in it."
            )

        if product.external:
            raise UnresolvableProduct(
                f"{species!r} is not archive data: its template is rooted at "
                f"{', '.join('$' + v for v in product.external)}, an svn/git "
                "software product checkout whose location is a property of your "
                "machine, not of the SAS. There is no build-time value to "
                "substitute, so this cannot be resolved here. See the "
                "$PRODUCT_ROOT notes in the README; a separate opt-in resolver "
                "taking an explicit product_root is the intended fix."
            )

        merged = {**self._release.defaults, **keys}

        missing = [k for k in product.required if k not in merged]
        if missing:
            raise MissingKeys(
                f"{species!r} requires {', '.join(missing)}. "
                f"Full key set: {', '.join(product.keys)}."
            )

        # Some derivations are satisfied by any one of a set of keys
        # (apgprefix takes either telescope or instrument).
        for group in product.any_of:
            if not any(merged.get(k) for k in group):
                raise MissingKeys(
                    f"{species!r} requires one of: {', '.join(group)}."
                )

        # Optional keys are deliberately NOT filled with a blank. Every key that
        # appears literally in a template is required, so `.format()` never needs
        # them; and the derivations already treat absence as their default. An
        # injected "" is worse than nothing -- apgprefix would read it as a
        # supplied-but-invalid telescope and raise.

        # Order matches sdss_access: brace substitution first, then derivations
        # (derivation markers contain no braces, so they survive .format()).
        resolved = product.template.format(**merged)
        resolved = self._apply_derivations(species, resolved, merged)

        # Collapse any empty segments left behind by blank derivations.
        while "//" in resolved:
            resolved = resolved.replace("//", "/")
        return resolved.strip("/")

    def _apply_derivations(self, species: str, template: str, keys: dict) -> str:
        for name in SPECIAL_RE.findall(template):
            try:
                fn = DERIVATIONS[name]
            except KeyError:
                raise UnresolvableProduct(
                    f"{species!r} uses unknown derivation @{name}|"
                ) from None
            value = fn(species, _env=self._release.derivation_env, **keys)
            template = template.replace(f"@{name}|", "" if value is None else str(value))
        return template

    def url(self, species: str, **keys: Any) -> str:
        """Resolve a product to its URL on the SAS."""
        if self.mirror:
            host = MIRROR_HOST
        else:
            host = PUBLIC_HOST if self._release.is_public else COLLAB_HOST
        return f"{host}/{self.path(species, **keys)}"

    @property
    def sas_root(self) -> _Path:
        """The local SAS root: explicit ``root``, else ``$SAS_BASE_DIR``, else ``~/sas``.

        ``$SAS_BASE_DIR`` is *read* here purely so that a machine already set up
        for ``sdss_access`` (a Utah mount, say) works without extra
        configuration. Nothing requires it, and nothing ever writes it -- path
        resolution itself never consults the environment at all.
        """
        if self.root:
            return _Path(self.root).expanduser()
        from os import environ

        if environ.get("SAS_BASE_DIR"):
            return _Path(environ["SAS_BASE_DIR"]).expanduser()
        return _Path.home() / "sas"

    def local(self, species: str, **keys: Any) -> _Path:
        """Resolve a product to a local filesystem path under :attr:`sas_root`."""
        return self.sas_root / self.path(species, **keys)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        rel = self._release
        access = "public" if rel.is_public else "collaboration"
        return (
            f"SDSS(release={self.release!r}, products={len(rel)}, "
            f"{access}, date={rel.release_date})"
        )


def known_releases() -> tuple[str, ...]:
    """Every SDSS-5 release this package knows about."""
    return releases()
