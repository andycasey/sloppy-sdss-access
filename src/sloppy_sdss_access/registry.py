"""The static SDSS-5 product registry.

Loaded once from a compiled JSON blob (see ``tools/build_registry.py``). Nothing
here reads or writes ``os.environ``, and every release is an independent,
immutable object -- so holding a DR19 and a DR20 registry side by side in one
session is unremarkable rather than a source of bugs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping

__all__ = ["Product", "Release", "load", "releases"]


# Pipeline versions associated with each release, applied as default keys.
#
# This is the mapping sdss/sdss_access#73 asks for: a user should be able to say
# `SDSS("dr19").path("astraAllStar", ...)` without having to remember that DR19
# means v_astra=0.6.0. The tree configs do not carry this, so it lives here.
#
# TODO: seeded only where a version is documented. Fill in the rest from the
# release coordinators before this is anything but a prototype.
RELEASE_DEFAULTS: Mapping[str, Mapping[str, str]] = {
    "dr19": {"run2d": "v6_1_3", "apred": "1.4", "v_astra": "0.6.0"},
}


@dataclass(frozen=True, slots=True)
class Product:
    """One data product species within one release."""

    species: str
    release: str
    template: str
    #: Compression suffix already named by the template (".gz"), else None.
    compression: str | None
    #: True when the SAS might store this compressed even though the template
    #: does not say so -- the only case worth probing for at runtime.
    may_be_compressed: bool
    keys: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
    formats: Mapping[str, str]
    derivations: tuple[str, ...]
    any_of: tuple[tuple[str, ...], ...]
    rooted: bool
    external: tuple[str, ...] = ()
    broken: tuple[str, ...] = ()

    @property
    def is_resolvable(self) -> bool:
        """False if the template references an env var this release never defines."""
        return not self.broken

    def describe(self) -> str:
        req = ", ".join(self.required) or "-"
        opt = ", ".join(self.optional) or "-"
        return (
            f"{self.species} ({self.release})\n"
            f"  template : {self.template}\n"
            f"  required : {req}\n"
            f"  optional : {opt}\n"
            f"  derived  : {', '.join(self.derivations) or '-'}\n"
            f"  compress : {self.compression or ('maybe' if self.may_be_compressed else 'no')}"
        )


@dataclass(frozen=True, slots=True)
class Release:
    """A single SDSS-5 release: a name, a date, and a set of products."""

    name: str
    phase: int
    release_date: str | None
    current: bool
    inherits: tuple[str, ...]
    products: Mapping[str, Product]
    defaults: Mapping[str, str] = field(default_factory=dict)
    #: Build-time-resolved roots that derivations need (see derive.spectrodir).
    derivation_env: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_public(self) -> bool:
        """Is this release readable without credentials *yet*?

        A DR only becomes public once its release date passes, so an
        unreleased DR still needs collaboration access.
        """
        from .auth import is_public

        return is_public(self.name, self.release_date)

    def __contains__(self, species: str) -> bool:
        return species in self.products

    def __len__(self) -> int:
        return len(self.products)

    def __iter__(self):
        return iter(self.products)


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    blob = files("sloppy_sdss_access.data").joinpath("registry.json").read_text()
    return json.loads(blob)


@lru_cache(maxsize=None)
def load(release: str) -> Release:
    """Load one release. Cached, so repeated construction is free."""
    key = release.lower().replace("-", "")
    data = _raw()["releases"]
    if key not in data:
        known = ", ".join(sorted(data))
        raise KeyError(
            f"{release!r} is not an SDSS-5 release. Known releases: {known}. "
            "DR7-DR12 (SDSS-I/II/III) are handled by the legacy sdss_access."
        )

    rel = data[key]
    products = {
        species: Product(
            species=species,
            release=key,
            template=p["template"],
            compression=p["compression"],
            may_be_compressed=p["may_be_compressed"],
            keys=tuple(p["keys"]),
            required=tuple(p["required"]),
            optional=tuple(p["optional"]),
            formats=p["formats"],
            derivations=tuple(p["derivations"]),
            any_of=tuple(tuple(g) for g in p.get("any_of", ())),
            rooted=p["rooted"],
            external=tuple(p.get("external", ())),
            broken=tuple(p.get("broken", ())),
        )
        for species, p in rel["products"].items()
    }

    return Release(
        name=key,
        phase=rel["phase"],
        release_date=rel["release_date"],
        current=rel["current"],
        inherits=tuple(rel["inherits"]),
        products=products,
        defaults=dict(RELEASE_DEFAULTS.get(key, {})),
        derivation_env=dict(rel.get("derivation_env", {})),
    )


def releases() -> tuple[str, ...]:
    """Every SDSS-5 release known to the registry."""
    return tuple(sorted(_raw()["releases"]))
