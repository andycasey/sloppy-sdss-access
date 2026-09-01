"""Reading a path backwards: keys out of a resolved path, and out of a glob.

No network. The glob tests stub the filesystem, because the point under test is
the key extraction, not fsspec.
"""

from __future__ import annotations

import re

import pytest

from sloppy_sdss_access import SDSS, Access, known_releases
from sloppy_sdss_access.derive import REVERSALS

dr19 = SDSS("dr19")


# ----------------------------------------------------------------------
# extract
# ----------------------------------------------------------------------


def test_extract_inverts_path():
    path = dr19.path("mwmStar", sdss_id=125678)
    assert dr19.extract("mwmStar", path) == {"v_astra": "0.6.0", "sdss_id": 125678}


def test_extract_accepts_a_url():
    url = dr19.url("mwmStar", sdss_id=125678)
    assert dr19.extract("mwmStar", url)["sdss_id"] == 125678


def test_extract_accepts_a_local_path():
    local = SDSS("dr19", root="/scratch/sas").local("mwmStar", sdss_id=125678)
    assert SDSS("dr19", root="/scratch/sas").extract("mwmStar", local) == {
        "v_astra": "0.6.0",
        "sdss_id": 125678,
    }


def test_extract_accepts_an_unknown_root():
    """A SAS mounted somewhere we were never told about still parses."""
    path = dr19.path("mwmStar", sdss_id=125678)
    assert dr19.extract("mwmStar", f"/somewhere/else/entirely/{path}") == {
        "v_astra": "0.6.0",
        "sdss_id": 125678,
    }


def test_extract_ignores_a_compression_suffix():
    """The SAS gzips files the template does not admit to; see resolve_uri."""
    path = dr19.path("mwmStar", sdss_id=125678)
    assert dr19.extract("mwmStar", path + ".gz")["sdss_id"] == 125678


def test_extract_tolerates_a_declared_suffix_the_file_does_not_carry():
    """The template says .fits.gz; the SAS does not always agree."""
    dr17 = SDSS("dr17")
    assert dr17.product("mangacube").compression == ".gz"
    plain = "dr17/manga/spectro/redux/v2_5_3/8485/stack/manga-8485-1901-LOGCUBE.fits"
    assert dr17.extract("mangacube", plain) == dr17.extract("mangacube", plain + ".gz")


def test_extract_returns_none_for_a_foreign_path():
    assert dr19.extract("mwmStar", "dr19/spectro/astra/0.6.0/summary/nope.fits") is None
    assert dr19.extract("mwmStar", dr19.path("mwmVisit", sdss_id=125678)) is None


def test_extract_recovers_a_key_that_only_a_derivation_writes():
    """specLite names fieldid nowhere except inside @pad_fieldid|."""
    assert "{fieldid}" not in dr19.product("specLite").template
    path = dr19.path("specLite", fieldid=101077, mjd=59797, catalogid=27021598108587618)
    assert dr19.extract("specLite", path) == {
        "run2d": "v6_1_3",
        "fieldid": 101077,
        "mjd": 59797,
        "catalogid": 27021598108587618,
    }


def test_extract_survives_collapsed_neighbouring_segments():
    """On a legacy run2d, spArc writes one segment where the template has three.

    @sptypefolder| and @fieldgrp| both collapse to nothing, and greedily
    @fieldgrp| would eat the fieldid segment and drop the key.
    """
    dr20 = SDSS("dr20")
    legacy = dr20.path("spArc", run2d="v6_1_3", fieldid=101077, br="b", id=4, frame=82)
    current = dr20.path("spArc", run2d="v6_2_0", fieldid=101077, br="b", id=4, frame=82)

    assert legacy.endswith("v6_1_3/101077/spArc-b4-00000082.fits.gz")
    assert current.endswith("v6_2_0/fields/101XXX/101077/spArc-b4-00000082.fits.gz")
    assert dr20.extract("spArc", legacy)["fieldid"] == 101077
    assert dr20.extract("spArc", current)["fieldid"] == 101077


def test_extract_reports_keys_in_template_order():
    """Not in whichever order the tie-breaking happened to visit them."""
    path = dr19.path("specLite", fieldid=101077, mjd=59797, catalogid=27021598108587618)
    assert list(dr19.extract("specLite", path)) == [
        "run2d",
        "fieldid",
        "mjd",
        "catalogid",
    ]


def test_extract_recovers_a_zero_padded_key():
    """A padded fieldid comes back as the int that produced it, not '000015'."""
    keys = dict(fieldid=15, mjd=59797, catalogid=27021598108587618)
    path = dr19.path("specLite", **keys)
    assert "/000015/" in path and "spec-000015-" in path  # padded both times
    assert dr19.extract("specLite", path)["fieldid"] == 15


def test_extract_leaves_an_unpadded_string_alone():
    """Nothing in the template re-pads this one, so int() would lose the zeros."""
    dr17 = SDSS("dr17")
    path = dr17.path("mangacube", drpver="v3_1_1", plate="08485", ifu="1901", wave="LOG")
    assert dr17.extract("mangacube", path)["plate"] == "08485"


def test_extract_refuses_what_path_refuses():
    from sloppy_sdss_access import UnresolvableProduct

    with pytest.raises(UnresolvableProduct):
        SDSS("dr17").extract("plateLines", "anything")


def test_pattern_is_compiled_once_per_template():
    """Patterns are cached on the template, so extract() in a loop is cheap."""
    assert SDSS("dr19").pattern("mwmStar") is SDSS("dr19").pattern("mwmStar")


# ----------------------------------------------------------------------
# every product, every release
# ----------------------------------------------------------------------

#: Plausible values, chosen so the derivations have something to chew on.
FAKE = {
    "healpix": 12345, "sdss_id": 125678, "cat_id": 27021598108587618,
    "catid": 27021598108587618, "catalogid": 27021598108587618,
    "configid": 123456, "tileid": 1028790, "plateid": 8485, "plate": 8485,
    "designid": 12345, "run2d": "v6_1_3", "run1d": "v6_1_3", "apred": "1.4",
    "v_astra": "0.6.0", "drpver": "1.1.1", "dapver": "1.1.1", "v_targ": "1.0.0",
    "telescope": "apo25m", "instrument": "apogee-n", "mjd": 59797,
    "fieldid": 101077, "field": 82, "obs": "apo", "coadd": "allepoch",
    "num": 12, "ftype": "fits", "task_id": 7, "chip": "a", "expnum": 12345,
    "kind": "Frame", "plugging": 1, "run": 1035, "rerun": 301, "camcol": 3,
    "filter": "r", "frame": 82, "ccd": 1, "rc": "a", "br": "b", "camrow": 1,
    "camnum": 1, "type": "star", "catalog": "gaia", "format": "ply", "id": 4,
}

TRUNCATED = re.compile(r"\{(\w+):[^{}]*\.\d+\}")


def _lossy(template: str) -> bool:
    """True if some key is *only* ever written truncated, e.g. ``{version:.2}``.

    Truncation throws characters away, so no inverse exists. It is fine when
    the template also writes the key in full somewhere (``nsa`` does), because
    extract() prefers the longest capture.
    """
    truncated = set(TRUNCATED.findall(template))
    full = set(re.findall(r"\{(\w+)\}", template))
    return bool(truncated - full)


def _products():
    for release in known_releases():
        sdss = SDSS(release)
        for species in sdss:
            product = sdss.product(species)
            if product.broken or product.external or _lossy(product.template):
                continue
            yield sdss, species, product


def test_every_product_round_trips():
    """path() -> extract() -> path() reproduces the path, for every product."""
    checked = 0
    for sdss, species, product in _products():
        keys = {key: FAKE.get(key, "xyz") for key in product.keys}
        path = sdss.path(species, **keys)
        recovered = sdss.extract(species, path)
        assert recovered is not None, f"{sdss.release}/{species}: {path}"
        assert path == sdss.path(species, **{**keys, **recovered}), (
            f"{sdss.release}/{species}"
        )
        checked += 1
    assert checked > 3000


def test_every_recoverable_key_comes_back():
    """A key the path actually shows must be extracted, for every product.

    The round-trip above cannot see a dropped key -- it re-resolves with the
    original keys underneath -- so this asserts coverage directly. "Recoverable"
    is structural: the key is written literally in the template, or a derivation
    in it declares that key. Everything else is unrecoverable by construction
    (`@apgprefix|` writes "ap" for both apo25m and apo1m).
    """
    for sdss, species, product in _products():
        keys = {key: FAKE.get(key, "xyz") for key in product.keys}
        recovered = sdss.extract(species, sdss.path(species, **keys))

        literal = {k for k in product.keys if "{%s}" % k in product.template
                   or "{%s:" % k in product.template}
        derived = {REVERSALS[d].key for d in product.derivations} & set(product.keys)

        assert (literal | derived) <= set(recovered), (
            f"{sdss.release}/{species} lost "
            f"{(literal | derived) - set(recovered)}: {product.template}"
        )


def test_every_derivation_declares_a_reversal():
    from sloppy_sdss_access.derive import DERIVATIONS

    assert set(REVERSALS) == set(DERIVATIONS)


# ----------------------------------------------------------------------
# glob
# ----------------------------------------------------------------------


class FakeFS:
    """Just enough fsspec to answer a glob."""

    def __init__(self, hits):
        self.hits = hits
        self.patterns = []

    def glob(self, pattern):
        self.patterns.append(pattern)
        return list(self.hits)


@pytest.fixture
def access(monkeypatch):
    def _make(hits):
        a = Access(dr19, cache=None)
        fs = FakeFS(hits)
        monkeypatch.setattr(type(a), "fs", property(lambda self: fs), raising=False)
        return a, fs

    return _make


def test_glob_returns_plain_strings(access):
    urls = [dr19.url("mwmStar", sdss_id=i) for i in (125678, 125679)]
    a, _ = access(urls)

    hits = a.glob("mwmStar", sdss_id="*")

    assert hits == urls
    assert all(type(hit) is str for hit in hits)


def test_glob_hits_extract_into_dicts(access):
    """The list of dicts asked for in #97, one extract() per hit."""
    urls = [dr19.url("mwmStar", sdss_id=i) for i in (125678, 125679)]
    a, _ = access(urls)

    hits = a.glob("mwmStar", sdss_id="*")

    assert [dr19.extract("mwmStar", hit) for hit in hits] == [
        {"v_astra": "0.6.0", "sdss_id": 125678},
        {"v_astra": "0.6.0", "sdss_id": 125679},
    ]


def test_extracted_values_can_be_fed_straight_back(access):
    a, _ = access([dr19.url("mwmStar", sdss_id=125678)])
    (hit,) = a.glob("mwmStar", sdss_id="*")
    assert dr19.url("mwmStar", **dr19.extract("mwmStar", hit)) == hit


def test_glob_expands_a_wildcard_through_a_derivation(access):
    """sdss_id groups into two directories, so a single '*' would not match."""
    a, fs = access([])
    a.glob("mwmStar", sdss_id="*")
    assert fs.patterns == [
        "https://data.sdss.org/sas/dr19/spectro/astra/0.6.0/spectra/star/"
        "*/*/mwmStar-0.6.0-*.fits"
    ]


def test_a_derivation_still_raises_when_there_is_no_wildcard_to_excuse_it():
    """A derivation blowing up on real keys is a real error, not a glob."""
    with pytest.raises(ValueError, match="not a known APOGEE instrument"):
        dr19.path("ap1D", instrument="not-an-instrument", mjd=59797, chip="a", num=42)
