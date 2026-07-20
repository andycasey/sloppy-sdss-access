"""Derived path segments -- ``sdss_access``'s "special functions", ported.

These compute a path *segment* from one or more keys (e.g. grouping directories
that keep any one folder from holding a million files).

Differences from ``sdss_access``:

* They are plain module-level functions, not methods on a 1,900-line class, so
  they are individually testable and importable.
* The keys each one consumes are *declared* (see ``DERIVATION_KEYS`` in
  ``tools/build_registry.py``) rather than recovered by AST-parsing the
  function's own source code at runtime.
* They never read ``os.environ``.

Behaviour is otherwise intentionally identical, bug-for-bug, so that resolved
paths can be diffed against the legacy implementation. Known upstream quirks are
marked ``BUG-COMPAT``.
"""

from __future__ import annotations

from typing import Any, Callable

Derivation = Callable[..., str]

DERIVATIONS: dict[str, Derivation] = {}


def derivation(fn: Derivation) -> Derivation:
    DERIVATIONS[fn.__name__] = fn
    return fn


# --------------------------------------------------------------------------
# grouping directories
# --------------------------------------------------------------------------


@derivation
def healpixgrp(species: str, **keys: Any) -> str:
    """HEALPix group directory: ``healpix // 1000``."""
    return f"{int(keys['healpix']) // 1000:d}"


@derivation
def cat_id_groups(species: str, **keys: Any) -> str:
    """Two-level grouping on catalogue id, ~1,000 files per folder at 10M sources."""
    cat_id = keys.get("cat_id", keys.get("catid"))
    if cat_id is None:
        raise KeyError("cat_id")
    cat_id = int(cat_id)
    return f"{(cat_id // 100) % 100:0>2.0f}/{cat_id % 100:0>2.0f}"


@derivation
def sdss_id_groups(species: str, **keys: Any) -> str:
    """Two-level grouping on SDSS id."""
    sdss_id = int(keys["sdss_id"])
    return f"{(sdss_id // 100) % 100:0>2.0f}/{sdss_id % 100:0>2.0f}"


@derivation
def configgrp(species: str, **keys: Any) -> str:
    """Configuration group directory, ``NNNNXX``."""
    configid = keys.get("configid")
    if not configid:
        return "0000XX"
    return f"{int(configid) // 100:0>4d}XX"


@derivation
def configsubmodule(species: str, **keys: Any) -> str:
    """Configuration submodule directory, ``NNNXXX``."""
    configid = keys.get("configid")
    if not configid:
        return "000XXX"
    return f"{int(configid) // 1000:0>3d}XXX"


@derivation
def tilegrp(species: str, **keys: Any) -> str:
    """LVM tile group directory, ``NNNNXX``."""
    tileid = keys.get("tileid")
    if not tileid:
        return "0000XX"
    if "*" in str(tileid):
        return f"{tileid}XX"
    # BUG-COMPAT: divides by 1000 but pads to 4, unlike configgrp's //100.
    return f"{int(tileid) // 1000:0>4d}XX"


@derivation
def platedir(species: str, **keys: Any) -> str:
    """Plate directory, ``NNNNXX/NNNNNN``."""
    plateid = int(keys["plateid"])
    return f"{plateid // 100:0>4d}XX/{plateid:0>6d}"


# --------------------------------------------------------------------------
# APOGEE
# --------------------------------------------------------------------------

_APG_PREFIX_BY_TELESCOPE = {"apo25m": "ap", "apo1m": "ap", "lco25m": "as"}
_APG_PREFIX_BY_INSTRUMENT = {"apogee-n": "ap", "apogee-s": "as"}


@derivation
def apgprefix(species: str, **keys: Any) -> str:
    """APOGEE file prefix (``ap``/``as``) from telescope or instrument."""
    telescope = keys.get("telescope")
    if telescope is not None:
        if telescope not in _APG_PREFIX_BY_TELESCOPE:
            raise ValueError(f"{telescope!r} is not a known APOGEE telescope")
        return _APG_PREFIX_BY_TELESCOPE[telescope]

    instrument = keys.get("instrument")
    if instrument is not None:
        if instrument not in _APG_PREFIX_BY_INSTRUMENT:
            raise ValueError(f"{instrument!r} is not a known APOGEE instrument")
        return _APG_PREFIX_BY_INSTRUMENT[instrument]

    return ""


@derivation
def component_default(species: str, **keys: Any) -> str:
    """Washington Multiplicity Catalog component, blank when absent."""
    component = keys.get("component", "")
    return str(component) if component is not None else ""


# --------------------------------------------------------------------------
# BOSS / idlspec2d
# --------------------------------------------------------------------------

_LEGACY_RUN2D = ("26", "103", "104")


def _is_legacy_layout(run2d: Any) -> bool:
    """True for run2d versions predating the reorganised BOSS directory layout."""
    run2d = str(run2d)
    return (
        "v5" in run2d
        or run2d in _LEGACY_RUN2D
        or "v6_0" in run2d
        or "v6_1" in run2d
    )


@derivation
def isplate(species: str, **keys: Any) -> str:
    """``p`` flag for the run2d versions that still used plates."""
    run2d = keys.get("run2d")
    if not run2d:
        return ""
    return "p" if run2d in ("v6_0_1", "v6_0_2", "v6_0_3", "v6_0_4") else ""


@derivation
def pad_fieldid(species: str, **keys: Any) -> str:
    """Zero-pad fieldid to 6 digits, except on the run2d versions that did not."""
    fieldid = keys.get("fieldid")
    run2d = keys.get("run2d")

    if not run2d and not fieldid:
        return ""
    fieldid = str(fieldid)
    if run2d in ("v6_0_1", "v6_0_2", "v6_0_3", "v6_0_4"):
        return fieldid
    return fieldid.zfill(6) if fieldid.isnumeric() else fieldid


@derivation
def fieldgrp(species: str, **keys: Any) -> str:
    """Field group directory, ``NNNXXX``, on the reorganised layout only."""
    fieldid = keys.get("fieldid")
    run2d = keys.get("run2d")
    if not fieldid:
        return ""
    if _is_legacy_layout(run2d):
        return ""
    fieldid = str(fieldid)
    return f"{int(fieldid) // 1000:0>3d}XXX" if fieldid.isnumeric() else fieldid


@derivation
def sptypefolder(species: str, **keys: Any) -> str:
    """Subfolder for the reorganised BOSS layout, by product species."""
    run2d = keys.get("run2d")
    species = species.lower()

    if not run2d or "v5" in str(run2d) or str(run2d) in _LEGACY_RUN2D:
        return ""

    if "v6_0" in str(run2d) or "v6_1" in str(run2d):
        if species in ("speclite_epoch", "specfull_epoch", "spallfield_epoch",
                       "spalllinefield_epoch"):
            return "epoch/spectra"
        return "epoch" if "epoch" in species else ""

    if species in ("fieldlist_epoch", "spall_epoch", "spall-lite_epoch",
                   "spallline_epoch"):
        return "summary/epoch"
    if species in ("speclite_epoch", "specfull_epoch", "spallfield_epoch",
                   "spalllinefield_epoch"):
        return "spectra/epoch"
    if species in ("conflist", "fieldlist", "spall", "spall-lite", "spallline"):
        return "summary/daily"
    if species in ("speclite", "specfull", "spallfield", "spalllinefield"):
        return "daily"
    return "fields"


@derivation
def spcoaddfolder(species: str, **keys: Any) -> str:
    """Subfolder for custom BOSS coadds."""
    run2d = keys.get("run2d")
    coadd = keys.get("coadd")
    if not run2d or _is_legacy_layout(run2d):
        return ""
    species = species.lower()
    if species in ("spall_coadd", "spall-lite_coadd", "spallline_coadd"):
        return "summary"
    if species in ("speclite_coadd", "specfull_coadd", "spallfield_coadd",
                   "spalllinefield_coadd"):
        return coadd
    return "fields"


@derivation
def spcoaddgrp(species: str, **keys: Any) -> str:
    """Field-group analog for custom BOSS coadds."""
    run2d = keys.get("run2d")
    if not run2d or _is_legacy_layout(run2d):
        return ""
    return keys.get("coadd")


@derivation
def epochflag(species: str, **keys: Any) -> str:
    """``-epoch`` suffix on the reorganised layout."""
    run2d = keys.get("run2d")
    return "" if _is_legacy_layout(run2d) else "-epoch"


@derivation
def spcoaddobs(species: str, **keys: Any) -> str:
    """Observatory suffix for custom coadds."""
    obs = keys.get("obs")
    run2d = keys.get("run2d")
    if not obs:
        return ""
    # BUG-COMPAT: upstream writes
    #     if (('v5' in run2d) or ... or (...) and obs.lower()) == 'apo':
    # where `== 'apo'` binds to the whole parenthesised expression, so the
    # comparison is `bool == 'apo'`, which is always False. The branch is
    # therefore dead upstream. Reproduced so paths match; see README.
    if False:  # noqa: SIM223  -- preserved dead branch, see above
        return ""
    if obs == "*":
        return obs
    return f"_{obs.lower()}"


# --------------------------------------------------------------------------
# MOS targeting
# --------------------------------------------------------------------------


def _mos_target_num(species: str, zp: int | None, prefix: str, **keys: Any) -> str:
    """Shared logic: MOS target files exist as both FITS and Parquet."""
    ftype = str(keys.get("ftype", "fits")).lower()
    if ftype not in ("fits", "parquet"):
        raise ValueError("ftype must be 'fits' or 'parquet'")
    if ftype == "parquet":
        return ""

    num = keys.get("num")
    if num is None:
        raise ValueError("missing required key 'num'")
    if str(num) == "*":
        return f"{prefix}*"

    num = int(num)
    if num > 0:
        return f"{prefix}{num:0>{zp}}" if zp is not None else f"{prefix}{num}"
    return ""


@derivation
def mos_target_num(species: str, **keys: Any) -> str:
    return _mos_target_num(species, zp=None, prefix="-", **keys)


@derivation
def mos_target_num2(species: str, **keys: Any) -> str:
    return _mos_target_num(species, zp=2, prefix="-", **keys)


@derivation
def mos_target_num3(species: str, **keys: Any) -> str:
    return _mos_target_num(species, zp=3, prefix="-", **keys)


# --------------------------------------------------------------------------
# SDSS-4 and earlier (plate-era)
# --------------------------------------------------------------------------


@derivation
def plateid6(species: str, **keys: Any) -> str:
    """Plate ID padded to 6 characters, except for 5-digit-plus plates."""
    plateid = int(keys["plateid"])
    return f"{plateid:0>6d}" if plateid < 10000 else f"{plateid:d}"


@derivation
def plategrp(species: str, **keys: Any) -> str:
    """Plate group directory, ``NNNNXX``."""
    plate = keys.get("plate", keys.get("plateid"))
    if not plate:
        return "XX"
    return f"{int(plate) // 100:0>4d}XX"


@derivation
def definitiondir(species: str, **keys: Any) -> str:
    """Design definition group directory, ``NNNNXX``."""
    return f"{int(keys['designid']) // 100:0>4d}XX"


@derivation
def spectrodir(species: str, **keys: Any) -> str:
    """SPECTRO_REDUX or BOSS_SPECTRO_REDUX, depending on ``run2d``.

    NOTE: this is the one derivation that returns a *root directory* rather than
    a path fragment. Upstream it reads ``os.environ`` directly; here the two
    candidate roots are resolved at build time and handed in via the reserved
    ``_env`` key, so the zero-environment-variable property survives.
    """
    env = keys.get("_env") or {}
    which = "SPECTRO_REDUX" if str(keys["run2d"]) in ("26", "103", "104") else "BOSS_SPECTRO_REDUX"
    try:
        return env[which]
    except KeyError:
        raise KeyError(
            f"{which} is not resolved for this release; spectrodir needs it"
        ) from None
