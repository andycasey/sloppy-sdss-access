"""Path resolution tests. No network, no environment variables."""

from __future__ import annotations

import os

import pytest

from sloppy_sdss_access import (
    MissingKeys,
    SDSS,
    UnknownProduct,
    UnresolvableProduct,
    known_releases,
    load,
)
from sloppy_sdss_access.derive import DERIVATIONS


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------


SDSS5_RELEASES = {"sdsswork", "ipl1", "ipl2", "ipl3", "ipl4", "dr18", "dr19", "dr20"}
SDSS4_RELEASES = {"dr13", "dr14", "dr15", "dr16", "dr17"}


def test_all_sdss5_releases_present():
    assert SDSS5_RELEASES <= set(known_releases())


def test_sdss4_releases_present():
    """EXPERIMENT: DR13-DR17 (SDSS-IV), which chain back to DR8."""
    assert SDSS4_RELEASES <= set(known_releases())


def test_pre_sdss4_releases_are_not_exposed():
    """DR7-DR12 are inherited from, but not offered as releases themselves."""
    assert not ({"dr7", "dr8", "dr9", "dr10", "dr11", "dr12"} & set(known_releases()))


def test_pre_sdss4_releases_are_rejected():
    """DR7-DR12 (SDSS-I/II/III) are inherited from, but not offered."""
    with pytest.raises(KeyError, match="legacy sdss_access"):
        load("dr12")


def test_every_release_has_products():
    for name in known_releases():
        assert len(load(name)) > 90


def test_inheritance_is_flattened():
    # dr19 inherits from dr18, so it must contain at least dr18's products.
    dr18, dr19 = load("dr18"), load("dr19")
    assert dr19.inherits == ("dr18",)
    assert len(dr19) > len(dr18)



def _synthetic_keys(product, ints, fixed, magnitude=12345):
    """Build a plausible key set, taking the type from the declared format spec.

    A spec containing "." is *string* precision (truncate), so those keys must
    be strings however integer-ish the name looks -- `version` uses ".4", and
    passing an int raises "Precision not allowed in integer format specifier".
    """
    keys = {}
    for key in product.keys:
        spec = product.formats.get(key, "")
        if key in fixed:
            keys[key] = fixed[key]
        elif "." in spec:
            keys[key] = f"{key}XXXX"
        elif key in ints or spec.endswith("d"):
            keys[key] = magnitude
        else:
            keys[key] = f"{key}X"
    return keys


# ----------------------------------------------------------------------
# no environment variables, anywhere
# ----------------------------------------------------------------------


def test_no_template_contains_an_environment_variable():
    """The entire point: $ENVVAR is resolved at build time."""
    offenders = []
    for name in known_releases():
        for species, product in load(name).products.items():
            if "$" in product.template and not (product.external or product.broken):
                offenders.append(f"{name}/{species}")
    assert not offenders, offenders


def test_resolution_does_not_touch_os_environ():
    before = dict(os.environ)
    SDSS("dr19").path("apStar", telescope="apo25m", healpix=12345, obj="X")
    assert dict(os.environ) == before


def test_releases_are_independent(monkeypatch):
    """sdss/sdss_access#34: two releases in one session must not interfere."""
    dr19, dr20 = SDSS("dr19"), SDSS("dr20")
    keys = dict(telescope="apo25m", healpix=12345, obj="X", apred="1.4")

    first = dr19.path("apStar", **keys)
    dr20.path("apStar", **keys)
    assert dr19.path("apStar", **keys) == first
    assert first.startswith("dr19/")


# ----------------------------------------------------------------------
# key handling
# ----------------------------------------------------------------------


def test_missing_required_key_raises_with_a_useful_message():
    with pytest.raises(MissingKeys, match="healpix"):
        SDSS("dr19").path("apStar", telescope="apo25m", obj="X")


def test_unknown_product_suggests_alternatives():
    with pytest.raises(UnknownProduct, match="Did you mean"):
        SDSS("dr19").path("apstar")


def test_release_defaults_fill_in_pipeline_versions():
    """sdss/sdss_access#73: DR19 implies its own pipeline versions."""
    dr19 = SDSS("dr19")
    assert dr19.defaults["v_astra"] == "0.6.0"
    assert dr19.path("astraAllStarASPCAP").endswith(
        "summary/astraAllStarASPCAP-0.6.0.fits.gz"
    )


def test_explicit_keys_override_release_defaults():
    got = SDSS("dr19").path("astraAllStarASPCAP", v_astra="9.9.9")
    assert "9.9.9" in got and "0.6.0" not in got


def test_optional_keys_may_be_omitted():
    """sdss/sdss_access#100: genuinely optional keys default rather than raising.

    `ap1D` supplies `instrument` literally, which already satisfies apgprefix,
    so `telescope` is redundant and may be left out.
    """
    dr19 = SDSS("dr19")
    assert "telescope" in dr19.product("ap1D").optional
    got = dr19.path(
        "ap1D", apred="1.4", chip="a", instrument="apogee-n", mjd=59797, num=1
    )
    assert "apCframe" not in got and got.endswith(".fits")


def test_broken_products_raise_instead_of_returning_a_literal_dollar_var():
    """sdss_access silently returns '$APOGEE_DATA_S/...' here; we refuse."""
    with pytest.raises(UnresolvableProduct, match=r"APOGEE_DATA_S"):
        SDSS("dr19").path("asR", mjd=59797, chip="a", num=1)


# ----------------------------------------------------------------------
# resolution
# ----------------------------------------------------------------------


def test_resolved_path_matches_the_real_sas_layout():
    # Verified against https://data.sdss5.org/sas/ on 2026-07-20.
    got = SDSS("dr19").path(
        "specLite", fieldid=15000, mjd=59146, catalogid=4375924756
    )
    assert got == (
        "dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/"
        "spec-015000-59146-4375924756.fits"
    )


def test_url_and_local_share_the_same_relative_path():
    dr19 = SDSS("dr19", root="/sas")
    keys = dict(telescope="apo25m", healpix=12345, obj="X")
    relative = dr19.path("apStar", **keys)
    assert dr19.url("apStar", **keys).endswith(relative)
    assert str(dr19.local("apStar", **keys)) == f"/sas/{relative}"


def test_search_finds_products_by_glob():
    hits = SDSS("dr19").search("astraAllStar*")
    assert "astraAllStarASPCAP" in hits


def test_every_resolvable_product_resolves_with_synthetic_keys():
    """Nothing in the registry is structurally un-resolvable."""
    ints = {
        "healpix", "cat_id", "catid", "sdss_id", "plateid", "plate", "configid",
        "tileid", "num", "designid", "mjd", "expnum", "frame", "specframe",
        "fiber", "camnum", "catalogid", "task_id", "seqno", "fieldid", "id",
        # SDSS-4 adds these with integer format specs.
        "apogeeid", "end", "fiberid", "field", "index", "irun", "lambda",
        "locationid", "muStart", "plugging", "run", "start", "stripe",
        # NB: "version" is NOT here -- its spec is ".2"/".4", i.e. string
        # precision (truncate), not an integer format.
    }
    fixed = {
        "telescope": "apo25m", "instrument": "apogee-n", "run2d": "v6_1_3",
        "ftype": "fits", "obs": "lco", "component": "", "coadd": "allepoch",
    }
    failures = []
    for name in known_releases():
        release, paths = load(name), SDSS(name)
        for species, product in release.products.items():
            if product.broken or product.external:
                continue
            keys = _synthetic_keys(product, ints, fixed, magnitude=10000)
            try:
                paths.path(species, **keys)
            except Exception as exc:
                failures.append(f"{name}/{species}: {type(exc).__name__}: {exc}")
    assert not failures, failures[:10]


# ----------------------------------------------------------------------
# derivations
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn,keys,expected",
    [
        ("healpixgrp", {"healpix": 12345}, "12"),
        ("cat_id_groups", {"cat_id": 27021598108587618}, "76/18"),
        ("sdss_id_groups", {"sdss_id": 1234}, "12/34"),
        ("configgrp", {"configid": 12345}, "0123XX"),
        ("configgrp", {}, "0000XX"),
        ("configsubmodule", {"configid": 12345}, "012XXX"),
        ("platedir", {"plateid": 7495}, "0074XX/007495"),
        ("apgprefix", {"telescope": "apo25m"}, "ap"),
        ("apgprefix", {"telescope": "lco25m"}, "as"),
        ("component_default", {}, ""),
        ("component_default", {"component": "A"}, "A"),
        ("isplate", {"run2d": "v6_0_2"}, "p"),
        ("isplate", {"run2d": "v6_1_3"}, ""),
        ("pad_fieldid", {"fieldid": 15000, "run2d": "v6_1_3"}, "015000"),
        ("pad_fieldid", {"fieldid": 15000, "run2d": "v6_0_4"}, "15000"),
        ("fieldgrp", {"fieldid": 15000, "run2d": "v6_2_0"}, "015XXX"),
        ("fieldgrp", {"fieldid": 15000, "run2d": "v6_1_3"}, ""),
        ("epochflag", {"run2d": "v6_1_3"}, ""),
        ("epochflag", {"run2d": "v6_2_0"}, "-epoch"),
        ("mos_target_num", {"num": 5}, "-5"),
        ("mos_target_num2", {"num": 5}, "-05"),
        ("mos_target_num3", {"num": 5}, "-005"),
        ("mos_target_num2", {"num": 5, "ftype": "parquet"}, ""),
        ("mos_target_num2", {"num": "*"}, "-*"),
    ],
)
def test_derivation(fn, keys, expected):
    assert DERIVATIONS[fn]("dummy", **keys) == expected


def test_apgprefix_rejects_an_unknown_telescope():
    with pytest.raises(ValueError, match="not a known APOGEE telescope"):
        DERIVATIONS["apgprefix"]("dummy", telescope="jwst")


def test_sptypefolder_depends_on_species():
    assert DERIVATIONS["sptypefolder"]("spAll", run2d="v6_2_0") == "summary/daily"
    assert DERIVATIONS["sptypefolder"]("specLite", run2d="v6_2_0") == "daily"
    assert DERIVATIONS["sptypefolder"]("anything", run2d="v6_1_3") == ""


# ----------------------------------------------------------------------
# regressions
# ----------------------------------------------------------------------


def test_optional_key_never_yields_a_malformed_path():
    """Regression: `fieldid` feeds @pad_fieldid| into the *filename*.

    Treating it as optional (because the derivation tolerates None) produced a
    silently malformed 'spec--59797-...fits'. Anything whose derivation output
    lands in a path segment must be required.
    """
    dr19 = SDSS("dr19")
    assert "fieldid" in dr19.product("specFull").required
    with pytest.raises(MissingKeys, match="fieldid"):
        dr19.path("specFull", mjd=59797, catalogid=27021598108587618)


def test_no_resolved_path_contains_an_empty_segment():
    """A blank derivation must never leave '--' or a doubled separator."""
    ints = {
        "healpix", "cat_id", "catid", "sdss_id", "plateid", "plate", "configid",
        "tileid", "num", "designid", "mjd", "expnum", "frame", "specframe",
        "fiber", "camnum", "catalogid", "task_id", "seqno", "fieldid", "id",
        # SDSS-4 adds these with integer format specs.
        "apogeeid", "end", "fiberid", "field", "index", "irun", "lambda",
        "locationid", "muStart", "plugging", "run", "start", "stripe",
        # NB: "version" is NOT here -- its spec is ".2"/".4", i.e. string
        # precision (truncate), not an integer format.
    }
    fixed = {
        "telescope": "apo25m", "instrument": "apogee-n", "run2d": "v6_2_0",
        "ftype": "fits", "obs": "lco", "component": "A", "coadd": "allepoch",
    }
    offenders = []
    for name in known_releases():
        release, paths = load(name), SDSS(name)
        for species, product in release.products.items():
            if product.broken or product.external:
                continue
            keys = _synthetic_keys(product, ints, fixed, magnitude=12345)
            got = paths.path(species, **keys)
            if "--" in got or "//" in got or "/-" in got:
                offenders.append(f"{name}/{species}: {got}")
    assert not offenders, offenders[:10]


def test_apgprefix_needs_either_telescope_or_instrument():
    """any_of groups: one of the pair must be supplied."""
    dr19 = SDSS("dr19")
    with pytest.raises(MissingKeys):
        dr19.path("apStar", healpix=12345, obj="X", apred="1.4")


def test_every_derivation_is_used_by_at_least_one_template():
    """Guards against dead code: apginst/mos_target_num_underscore were removed."""
    from sloppy_sdss_access.derive import DERIVATIONS

    used = {
        d
        for name in known_releases()
        for product in load(name).products.values()
        for d in product.derivations
    }
    assert not (set(DERIVATIONS) - used), set(DERIVATIONS) - used


def test_sas_root_precedence(monkeypatch, tmp_path):
    """explicit root > $SAS_BASE_DIR > ~/sas -- read only, never written."""
    monkeypatch.delenv("SAS_BASE_DIR", raising=False)
    assert SDSS("dr19").sas_root == __import__("pathlib").Path.home() / "sas"

    monkeypatch.setenv("SAS_BASE_DIR", str(tmp_path))
    assert SDSS("dr19").sas_root == tmp_path
    assert SDSS("dr19", root="/explicit").sas_root == __import__("pathlib").Path("/explicit")


def test_path_resolution_ignores_sas_base_dir(monkeypatch, tmp_path):
    """Only local() consults it; path()/url() never do."""
    keys = dict(telescope="apo25m", healpix=12345, obj="X", apred="1.4")
    monkeypatch.delenv("SAS_BASE_DIR", raising=False)
    without = SDSS("dr19").path("apStar", **keys)
    monkeypatch.setenv("SAS_BASE_DIR", str(tmp_path))
    assert SDSS("dr19").path("apStar", **keys) == without


def test_external_products_refuse_to_resolve():
    """Regression: `external` products are rooted at a software checkout.

    They were emitting a path containing a literal `$PRODUCT_ROOT` -- exactly
    the silent-failure mode this package exists to avoid, and exactly what the
    README already claimed was prevented.
    """
    dr17 = SDSS("dr17")
    assert dr17.product("plateHoles").external == ("PRODUCT_ROOT",)
    with pytest.raises(UnresolvableProduct, match="PRODUCT_ROOT"):
        dr17.path("plateHoles", plateid=8000)


def test_no_resolved_path_ever_contains_a_literal_envvar():
    """Sweep: nothing resolvable may leak a '$VAR' into its output."""
    ints = {
        "healpix", "cat_id", "catid", "sdss_id", "plateid", "plate", "configid",
        "tileid", "num", "designid", "mjd", "expnum", "frame", "specframe",
        "fiber", "camnum", "catalogid", "task_id", "seqno", "fieldid", "id",
        "apogeeid", "end", "fiberid", "field", "index", "irun", "lambda",
        "locationid", "muStart", "plugging", "run", "start", "stripe",
    }
    fixed = {
        "telescope": "apo25m", "instrument": "apogee-n", "run2d": "v6_2_0",
        "ftype": "fits", "obs": "lco", "component": "A", "coadd": "allepoch",
    }
    offenders = []
    for name in known_releases():
        release, paths = load(name), SDSS(name)
        for species, product in release.products.items():
            keys = _synthetic_keys(product, ints, fixed)
            try:
                got = paths.path(species, **keys)
            except (MissingKeys, UnresolvableProduct):
                continue
            if "$" in got:
                offenders.append(f"{name}/{species}: {got}")
    assert not offenders, offenders[:10]


# ----------------------------------------------------------------------
# the registry builder must never destroy a shipped registry
# ----------------------------------------------------------------------


def test_builder_refuses_to_run_without_source_configs(monkeypatch, tmp_path):
    """Regression: running the console script bare in an *installed* env used to
    rebuild an empty registry over the shipped one, leaving 0 products."""
    from sloppy_sdss_access import _build

    monkeypatch.setattr(_build, "HERE", tmp_path)  # no .cfg files here
    assert _build.missing_configs() == list(_build.RELEASES)
    with pytest.raises(SystemExit, match="No tree configs"):
        _build.require_configs()


def test_builder_guard_passes_with_configs_present():
    from sloppy_sdss_access import _build

    assert _build.missing_configs() == []
    _build.require_configs()  # must not raise


def test_shipped_registry_is_not_degenerate():
    """Every release must carry products; a zero-product release means a bad build."""
    empty = [name for name in known_releases() if len(load(name)) == 0]
    assert not empty, empty
