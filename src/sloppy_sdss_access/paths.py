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
from functools import lru_cache
from pathlib import Path as _Path
from typing import Any, Iterator, NamedTuple

from .derive import DERIVATIONS, REVERSALS
from .registry import Product, Release, load, releases

__all__ = ["SDSS", "UnknownProduct", "MissingKeys", "UnresolvableProduct"]

SPECIAL_RE = re.compile(r"@(\w+)\|")
#: A ``{key}``/``{key:spec}`` placeholder, or an ``@derivation|`` marker.
TOKEN_RE = re.compile(r"\{([^{}]*)\}|@(\w+)\|")

#: Suffixes the SAS appends without always saying so in the template.
COMPRESSION_SUFFIXES = (".gz", ".bz2", ".fz", ".zip", ".Z")

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
        globbing = any("*" in str(v) for v in keys.values())
        for name in SPECIAL_RE.findall(template):
            try:
                fn = DERIVATIONS[name]
            except KeyError:
                raise UnresolvableProduct(
                    f"{species!r} uses unknown derivation @{name}|"
                ) from None
            try:
                value = fn(species, _env=self._release.derivation_env, **keys)
            except Exception:
                # A wildcard cannot be pushed through a derivation -- there is
                # no answer to `int("*") // 1000`. When the caller is globbing,
                # stand the segment in with a wildcard of the right *shape*:
                # `@sdss_id_groups|` spans two directory levels, and a single
                # `*` does not cross a `/`. Without a wildcard in play the
                # failure is a real one, so it propagates.
                if not globbing:
                    raise
                value = REVERSALS[name].wildcard
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
    # the other direction: path -> keys
    # ------------------------------------------------------------------

    def pattern(self, species: str) -> re.Pattern[str]:
        """The compiled regex that reads this product's paths *backwards*.

        Every key is a capture group, so this is the inverse of :meth:`path`.
        Mostly of interest to :meth:`extract`, but exposed because matching a
        few million filenames is faster done directly against the pattern.
        """
        return _compile(self._resolvable(species).template)[0]

    def extract(self, species: str, path: str | _Path) -> dict[str, Any] | None:
        """Recover the keys that produced ``path`` -- the inverse of :meth:`path`.

        ``path`` may be a SAS-relative path, a full URL, or an absolute path
        under a local SAS root; the release-specific prefix is stripped either
        way::

            dr19.extract("mwmStar", "dr19/spectro/astra/0.6.0/spectra/star/"
                                    "56/78/mwmStar-0.6.0-125678.fits")
            {'v_astra': '0.6.0', 'sdss_id': 125678}

        Returns ``None`` if the path is not one this product could have
        produced -- which makes it a membership test as well as a parser.

        Values come back as :class:`int` where that round-trips exactly
        (``sdss_id`` above), and as :class:`str` where it would not (a
        zero-padded ``fieldid`` on a template that does no padding of its own).
        Feeding the result straight back into :meth:`path` reproduces the input.

        Keys that leave no trace in the path cannot be recovered: an APOGEE
        ``telescope`` of ``apo25m`` and ``apo1m`` both write ``ap``, so
        ``@apgprefix|`` yields no ``telescope``. Nor can a key the template
        truncates -- DR17's ``atlas_*`` write ``{version:.2}`` -- and there you
        get the longest surviving fragment rather than nothing.
        """
        product = self._resolvable(species)
        regex, groups = _compile(product.template)

        relative = self._strip_prefix(str(path))
        match = regex.fullmatch(relative)
        if match is None:
            # A local SAS root we do not know about, or an s3 bucket prefix.
            match = re.fullmatch(f"(?:.*?/)?{regex.pattern}", relative)
        if match is None:
            return None

        # Where a key is captured more than once, take the best witness of it.
        # Keys named literally in the template beat keys recovered from a
        # derived segment -- `{plateid:0>4}` is the plate id, whereas
        # `@platedir|` merely contains it -- and, among equals, the longest
        # capture beats a truncated one (`{version:.4}` over `{version:.2}`).
        def best(group: _Group) -> tuple[int, int]:
            return (group.rank, -len(match.group(group.name) or ""))

        values: dict[str, Any] = {}
        for group in sorted(groups, key=best):
            if group.key is None:
                continue
            text = match.group(group.name)
            if not text:  # an absent optional group, or a collapsed segment
                continue
            values.setdefault(group.key, group.parse(text))
        # Report in template order, not in whichever order the tie-breaking
        # happened to visit them.
        return {g.key: values[g.key] for g in groups if g.key in values}

    def _resolvable(self, species: str) -> Product:
        """The product, having checked it is one we can template at all."""
        product = self.product(species)
        if product.broken or product.external:
            self.path(species)  # raises UnresolvableProduct with the full story
        return product

    def _strip_prefix(self, text: str) -> str:
        """Reduce a URL or an absolute local path to a SAS-relative one."""
        text = text.split("://", 1)[-1]
        if "/sas/" in text:
            return text.split("/sas/", 1)[1]
        root = str(self.sas_root)
        if text.startswith(root):
            return text[len(root) :].lstrip("/")
        return text.lstrip("/")

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        rel = self._release
        access = "public" if rel.is_public else "collaboration"
        return (
            f"SDSS(release={self.release!r}, products={len(rel)}, "
            f"{access}, date={rel.release_date})"
        )


# ----------------------------------------------------------------------
# template -> regex
# ----------------------------------------------------------------------


class _Group(NamedTuple):
    """One capture group in a product's reverse pattern.

    ``rank`` breaks ties when a key is captured more than once: a plain
    ``{run}`` is a better witness than ``{run:0>6}``, which is better than a
    derived segment that merely contains the value.
    """

    name: str
    key: str | None
    parse: Any
    rank: int


_PLAIN, _FORMATTED, _DERIVED = 0, 1, 2


def _parse_value(text: str, spec: str) -> Any:
    """Type a captured value, but only where doing so round-trips.

    ``"125678"`` is an ``sdss_id`` and comes back as an int. ``"008485"`` under
    a template that says ``{plateid:0>4}`` is also an int, because the template
    will pad it again. ``"008485"`` under a template that does *no* padding
    stays a string, because ``int`` would lose the zeros for good.
    """
    if not text.isdigit():
        return text
    if text == "0" or not text.startswith("0") or "0" in spec.split(">")[0]:
        return int(text)
    return text


@lru_cache(maxsize=None)
def _compile(template: str) -> tuple[re.Pattern[str], tuple[_Group, ...]]:
    """Turn a tree template into the regex that reads its paths backwards.

    ``{key}`` becomes a capture group, ``@derivation|`` becomes the pattern its
    :class:`~sloppy_sdss_access.derive.Reversal` declares, and a key or
    derivation appearing twice becomes a backreference -- which is not just an
    economy: it is what pins down ``specLite``, whose ``@pad_fieldid|`` is
    otherwise ambiguous against the ``@isplate|`` flag glued to its right.
    """
    parts: list[str] = []
    groups: list[_Group] = []
    seen: dict[str, str] = {}
    position = 0

    for token in TOKEN_RE.finditer(template):
        parts.append(re.escape(template[position : token.start()]))
        position = token.end()
        brace, derivation = token.group(1), token.group(2)

        # Two occurrences share a group only if they render identically:
        # `{run}` and `{run:0>6}` are the same key but not the same text.
        marker = f"@{derivation}|" if brace is None else f"{{{brace}}}"

        if marker in seen:
            parts.append(f"(?P={seen[marker]})")
            continue

        name = f"g{len(groups)}"
        seen[marker] = name

        if brace is not None:
            key, _, spec = brace.partition(":")
            parts.append(f"(?P<{name}>[^/]+?)")
            groups.append(
                _Group(
                    name,
                    key,
                    lambda t, s=spec: _parse_value(t, s),
                    _FORMATTED if spec else _PLAIN,
                )
            )
            continue

        try:
            reversal = REVERSALS[derivation]
        except KeyError:
            raise UnresolvableProduct(
                f"template uses unknown derivation @{derivation}|: {template}"
            ) from None

        group = f"(?P<{name}>{reversal.pattern})"
        if reversal.collapsible and template[position : position + 1] == "/":
            # path() squashes the `//` an empty segment leaves behind, so the
            # separator has to be optional along with the segment itself.
            #
            # A segment that reveals no key is matched *lazily*, so that when
            # neighbouring segments have both collapsed the text goes to the
            # one that does reveal a key. On a legacy run2d, `spArc` writes one
            # segment where the template has three; greedily, `@fieldgrp|`
            # would eat it and the fieldid would be lost.
            group = f"(?:{group}/)?" if reversal.key else f"(?:{group}/)??"
            position += 1
        parts.append(group)
        groups.append(_Group(name, reversal.key, reversal.parse, _DERIVED))

    # Templates and the SAS disagree about compression in both directions (see
    # Access.resolve_uri), so a declared suffix is optional and an undeclared
    # one is allowed.
    tail = template[position:]
    declared = next((s for s in COMPRESSION_SUFFIXES if tail.endswith(s)), None)
    if declared:
        parts.append(re.escape(tail[: -len(declared)]))
        parts.append(f"(?:{re.escape(declared)})?")
    else:
        parts.append(re.escape(tail))
        parts.append("(?:%s)?" % "|".join(re.escape(s) for s in COMPRESSION_SUFFIXES))
    return re.compile("".join(parts)), tuple(groups)


def known_releases() -> tuple[str, ...]:
    """Every SDSS-5 release this package knows about."""
    return releases()
