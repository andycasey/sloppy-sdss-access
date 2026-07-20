"""Differential test: resolve every SDSS-5 product both ways and compare.

Resolves each product with the legacy ``sdss_access.path.Path`` and with
``sloppy_sdss_access.SDSS``, using identical keys, and reports any divergence.

Each product is resolved under **several key scenarios**, not one. That matters:
an earlier version of this script pinned ``run2d="v6_1_3"``, which makes every
"reorganised BOSS layout" branch in ``derive.py`` dead code. Ten of the twenty-two
derivations then returned a single constant for the whole run, and five were
never called at all -- so half of ``derive.py`` could have been replaced with
hardcoded strings and this check would still have passed.

It therefore also enforces a **coverage gate**: every derivation must be exercised,
and must produce at least two distinct outputs across the run. A green result with
no coverage gate is not evidence of much.

Usage::

    python tools/parity_check.py [release ...]

Requires the real ``sdss-access`` installed alongside this package; the two have
distinct module names, so they coexist in one environment.
"""

from __future__ import annotations

import os
import sys
import warnings
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

os.environ.setdefault("SAS_BASE_DIR", "/tmp/sas-parity")
os.makedirs(os.environ["SAS_BASE_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sloppy_sdss_access import SDSS, load  # noqa: E402
from sloppy_sdss_access import derive  # noqa: E402

# Keys that must be integers, because a derivation or format spec does maths.
INT_KEYS = {
    "healpix", "cat_id", "catid", "sdss_id", "plateid", "plate", "configid",
    "tileid", "num", "designid", "mjd", "expnum", "frame", "specframe",
    "fiber", "camnum", "catalogid", "task_id", "seqno", "fieldid", "id",
}

# Scenarios chosen to drive every branch in derive.py:
#   run2d       -> legacy vs v6_0 vs v6_1 vs reorganised layout
#   telescope   -> ap/as prefixes, and apo1m
#   obs         -> per-observatory and wildcard coadds
#   ftype       -> the parquet short-circuit in mos_target_num*
#   magnitude   -> different //100 and //1000 grouping directories
SCENARIOS = [
    {"run2d": "v6_1_3", "telescope": "apo25m", "instrument": "apogee-n",
     "obs": "lco", "ftype": "fits", "component": "", "coadd": "allepoch",
     "magnitude": 10_000},
    {"run2d": "v6_2_0", "telescope": "lco25m", "instrument": "apogee-s",
     "obs": "apo", "ftype": "fits", "component": "A", "coadd": "custom",
     "magnitude": 4_375_924},
    {"run2d": "v6_0_4", "telescope": "apo1m", "instrument": "apogee-n",
     "obs": "", "ftype": "parquet", "component": "Ab", "coadd": "daily",
     "magnitude": 137},
    {"run2d": "26", "telescope": "apo25m", "instrument": "apogee-s",
     "obs": "*", "ftype": "fits", "component": "", "coadd": "allepoch",
     "magnitude": 999_999},
    {"run2d": "v5_13_2", "telescope": "lco25m", "instrument": "apogee-n",
     "obs": "lco", "ftype": "fits", "component": "B", "coadd": "custom",
     "magnitude": 55},
]


def keys_for(product, scenario: dict, salt: int) -> dict:
    keys = {}
    for key in product.keys:
        if key in scenario:
            keys[key] = scenario[key]
        elif key in INT_KEYS:
            keys[key] = scenario["magnitude"] + salt
        else:
            keys[key] = f"{key}X{salt}"
    return keys


# These derivations are only ever reached by ``external`` products -- confSummary
# files under $SDSSCORE_DIR and plateHoles under $PLATELIST_DIR. Those live
# outside the SAS data tree, so neither implementation can resolve them here and
# parity necessarily skips them. They are covered by unit tests in
# tests/test_paths.py instead, so exempt them from the gate rather than pretending.
EXTERNAL_ONLY = {
    "configgrp", "configsubmodule", "platedir",
    # SDSS-4: plate/design products all live under $PRODUCT_ROOT.
    "definitiondir", "plategrp", "plateid6",
}


class CoverageTracker:
    """Wrap the derivations to record which ones actually ran, and their outputs."""

    def __init__(self) -> None:
        self.outputs: dict[str, set[str]] = defaultdict(set)
        self._original = dict(derive.DERIVATIONS)

    def install(self) -> None:
        for name, fn in self._original.items():
            derive.DERIVATIONS[name] = self._wrap(name, fn)

    def restore(self) -> None:
        derive.DERIVATIONS.clear()
        derive.DERIVATIONS.update(self._original)

    def _wrap(self, name, fn):
        def wrapped(species, **keys):
            value = fn(species, **keys)
            self.outputs[name].add(str(value))
            return value
        return wrapped

    def report(self) -> tuple[list[str], list[str]]:
        never = sorted(set(self._original) - set(self.outputs) - EXTERNAL_ONLY)
        constant = sorted(n for n, vals in self.outputs.items() if len(vals) < 2)
        return never, constant


def norm(path: str) -> str:
    """Drop compression suffixes.

    Legacy probes the filesystem and may add or strip one; nothing exists on
    this machine, so the suffix carries no signal. NOTE: this makes the check
    blind to sdss/sdss_access#66 (compressed-file resolution) by construction.
    """
    for suffix in (".gz", ".bz2", ".zip", ".fz"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    return path.strip("/")


def main(releases: list[str]) -> int:
    from sdss_access.path import Path as LegacyPath

    tracker = CoverageTracker()
    tracker.install()

    grand = Counter()
    diffs: list[tuple[str, str, dict, str, str]] = []
    unresolved: list[tuple[str, str, str, str]] = []
    errors: list[str] = []

    try:
        for release in releases:
            rel = load(release)
            new = SDSS(release)
            try:
                legacy = LegacyPath(release=release, preserve_envvars=False)
            except Exception as exc:
                errors.append(f"{release}: cannot construct legacy Path ({exc})")
                continue

            counts = Counter()
            base = os.environ["SAS_BASE_DIR"].rstrip("/")

            for i, (species, product) in enumerate(sorted(rel.products.items())):
                if product.broken or product.external:
                    counts["skipped"] += 1
                    continue
                if species not in legacy.templates:
                    counts["not in legacy"] += 1
                    continue

                for si, scenario in enumerate(SCENARIOS):
                    keys = keys_for(product, scenario, salt=i + si)

                    try:
                        mine = new.path(species, **keys)
                    except Exception as exc:
                        counts["new error"] += 1
                        errors.append(
                            f"{release}/{species} [scenario {si}]: "
                            f"new raised {type(exc).__name__}: {exc}"
                        )
                        continue

                    try:
                        theirs = legacy.full(species, **keys)
                    except Exception as exc:
                        counts["legacy error"] += 1
                        errors.append(
                            f"{release}/{species} [scenario {si}]: "
                            f"legacy raised {type(exc).__name__}: {exc}"
                        )
                        continue

                    theirs_rel = (
                        theirs[len(base):].lstrip("/")
                        if theirs.startswith(base) else theirs
                    )

                    if norm(mine) == norm(theirs_rel):
                        counts["match"] += 1
                    elif theirs_rel.startswith("$") or "/$" in theirs_rel:
                        # Legacy could not expand an env var and returned a path
                        # with a literal "$VAR" in it. Record it, but it is not a
                        # mismatch of two valid answers.
                        counts["legacy unresolved"] += 1
                        unresolved.append((release, species, mine, theirs_rel))
                    else:
                        counts["DIFFER"] += 1
                        diffs.append((release, species, keys, mine, theirs_rel))

            grand.update(counts)
            print(f"  {release:10s} " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    finally:
        tracker.restore()

    print("\n  TOTAL: " + "  ".join(f"{k}={v}" for k, v in sorted(grand.items())))

    # ---- coverage gate -------------------------------------------------
    never, constant = tracker.report()
    print(f"\n  Derivation coverage: {len(tracker.outputs)}/{len(derive.DERIVATIONS)} exercised")
    if never:
        print(f"    NEVER CALLED    : {', '.join(never)}")
    if constant:
        print(f"    SINGLE OUTPUT   : {', '.join(constant)}")
    if not never and not constant:
        print("    every derivation ran and produced >=2 distinct outputs")

    if diffs:
        print(f"\n  {len(diffs)} divergences (first 20):")
        for release, species, keys, mine, theirs in diffs[:20]:
            print(f"\n    {release}/{species}  keys={keys}")
            print(f"      new    : {mine}")
            print(f"      legacy : {theirs}")

    if unresolved:
        species_hit = sorted({f"{r}/{sp}" for r, sp, _m, _t in unresolved})
        print(
            f"\n  {len(unresolved)} resolutions where LEGACY returned a literal $VAR "
            f"({len(species_hit)} products):"
        )
        for release, sp, mine, theirs in unresolved[:4]:
            print(f"    {release}/{sp}")
            print(f"      new    : {mine}")
            print(f"      legacy : {theirs}")

    if errors:
        print(f"\n  {len(errors)} errors (first 20):")
        for line in errors[:20]:
            print(f"    {line}")

    # Fail on divergence, on any error, and on inadequate coverage.
    ok = not diffs and not errors and not never and not constant
    print("\n  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:] or [
        "dr18", "dr19", "dr20", "ipl1", "ipl2", "ipl3", "ipl4", "sdsswork",
        "dr13", "dr14", "dr15", "dr16", "dr17",
    ]
    raise SystemExit(main(args))
