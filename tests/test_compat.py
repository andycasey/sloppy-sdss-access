"""Drop-in compatibility with the legacy ``sdss_access`` API.

The distribution is `sloppy-sdss-access` but the module is `sdss_access`, so code
written against the original keeps importing. These tests pin how far that
compatibility actually goes.

The reference values were captured from the real `sdss-access` package running
in a separate virtualenv (see tools/_legacy_resolve.py for why it must be
separate).
"""

from __future__ import annotations

import pytest

from sloppy_sdss_access import (
    AccessError,
    CurlAccess,
    MissingKeys,
    Path,
    RsyncAccess,
    SDSSPath,
)

SPEC = dict(fieldid=15000, mjd=59146, catalogid=4375924756, run2d="v6_1_3")

# Verified byte-identical against sdss-access on 2026-07-20.
LEGACY_LOCATION = (
    "dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/"
    "spec-015000-59146-4375924756.fits"
)
LEGACY_URL = f"https://data.sdss.org/sas/{LEGACY_LOCATION}"


def test_legacy_names_are_importable():
    assert SDSSPath is Path
    assert issubclass(AccessError, Exception)


def test_full_matches_legacy(tmp_path):
    got = Path(release="dr19", root=tmp_path).full("specLite", **SPEC)
    assert got == str(tmp_path / LEGACY_LOCATION)


def test_location_matches_legacy():
    assert Path(release="dr19").location("specLite", **SPEC) == LEGACY_LOCATION


def test_url_matches_legacy():
    """Public DRs resolve to data.sdss.org, as sdss_access does."""
    assert Path(release="dr19").url("specLite", **SPEC) == LEGACY_URL


def test_collaboration_releases_use_the_sdss5_host():
    url = Path(release="sdsswork").url("mwmStar", v_astra="0.6.0", sdss_id=103020004)
    assert url.startswith("https://data.sdss5.org/sas/")


def test_name_and_dir(tmp_path):
    p = Path(release="dr19", root=tmp_path)
    assert p.name("specLite", **SPEC) == "spec-015000-59146-4375924756.fits"
    assert p.dir("specLite", **SPEC).endswith("015000/59146")


def test_templates_and_lookup_helpers():
    p = Path(release="dr19")
    assert len(p.templates) > 300
    assert p.has_name("apStar")
    assert not p.has_name("nonsuch")
    assert set(p.lookup_keys("apStar")) == {"apred", "healpix", "obj", "telescope"}
    assert "apStar" in p.lookup_names()


def test_legacy_control_kwargs_are_tolerated(tmp_path):
    """force_module/skip_tag_check were legacy-only; accept and ignore them."""
    p = Path(release="dr19", root=tmp_path)
    assert p.location("specLite", skip_tag_check=True, force_module=False, **SPEC) == (
        LEGACY_LOCATION
    )


def test_full_passthrough(tmp_path):
    """Legacy allowed Path.full('', full=...) as an identity."""
    assert Path(release="dr19", root=tmp_path).full("specLite", full="/x/y.fits") == "/x/y.fits"


def test_constructor_accepts_and_ignores_dead_arguments():
    """public/verbose/force_modules/preserve_envvars no longer mean anything."""
    p = Path(
        release="dr19", public=True, verbose=True,
        force_modules=True, preserve_envvars=True,
    )
    assert p.location("specLite", **SPEC) == LEGACY_LOCATION


# ----------------------------------------------------------------------
# deliberate behaviour changes
# ----------------------------------------------------------------------


def test_missing_key_raises_instead_of_producing_a_malformed_path():
    with pytest.raises(MissingKeys):
        Path(release="dr19").location("specFull", mjd=59797, catalogid=1)


def test_release_defaults_make_run2d_optional():
    """Legacy raised KeyError for a missing run2d; DR19 now implies it."""
    assert Path(release="dr19").location(
        "specLite", fieldid=15000, mjd=59146, catalogid=4375924756
    ) == LEGACY_LOCATION


def test_pre_sdss4_releases_are_rejected():
    with pytest.raises(KeyError):
        Path(release="dr12")


@pytest.mark.parametrize("cls", [RsyncAccess, CurlAccess])
def test_rsync_and_curl_raise_with_a_pointer_to_the_replacement(cls):
    with pytest.raises(NotImplementedError, match="fetch_many"):
        cls()


def test_path_and_sdss_are_different_objects():
    """`Path` is the legacy shim; `SDSS` is the native API.

    They resolve identically but expose different method names.
    """
    from sloppy_sdss_access import SDSS, Path

    assert Path is not SDSS
    assert SDSS("dr19").path("specLite", **SPEC) == Path("dr19").location(
        "specLite", **SPEC
    )
