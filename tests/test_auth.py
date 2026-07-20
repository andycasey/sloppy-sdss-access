"""Authentication tests. No network."""

from __future__ import annotations

import datetime
import warnings

import pytest

from sloppy_sdss_access import load
from sloppy_sdss_access.auth import AuthError, Credentials, is_public, resolve

@pytest.fixture
def netrc_file(tmp_path):
    path = tmp_path / ".netrc"
    path.write_text(
        "machine data.sdss5.org\n  login netrcuser\n  password netrcpw\n"
    )
    path.chmod(0o600)
    return path


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch):
    """Keep a developer's real SDSS_USER out of these tests."""
    monkeypatch.delenv("SDSS_USER", raising=False)
    monkeypatch.delenv("SDSS_PASSWORD", raising=False)


# ----------------------------------------------------------------------
# which releases need credentials
# ----------------------------------------------------------------------


def test_public_requires_a_release_date_that_has_passed():
    past = datetime.date(2020, 1, 1)
    assert is_public("dr19", "2025-07-10", today=datetime.date(2026, 1, 1))
    assert not is_public("dr19", "2025-07-10", today=past)


def test_unreleased_dr_is_not_public():
    """DR20 is dated 2026-07-30, so it still needs collaboration access."""
    assert not is_public("dr20", "2026-07-30", today=datetime.date(2026, 7, 20))
    assert is_public("dr20", "2026-07-30", today=datetime.date(2026, 8, 1))


def test_work_and_ipl_releases_are_never_public():
    assert not is_public("sdsswork", None)
    assert not is_public("ipl4", "2025-07-15")
    assert not load("sdsswork").is_public
    assert not load("ipl4").is_public


def test_released_drs_are_public():
    assert load("dr18").is_public
    assert load("dr19").is_public


# ----------------------------------------------------------------------
# credential resolution order
# ----------------------------------------------------------------------


def test_explicit_credentials_win(monkeypatch, netrc_file):
    monkeypatch.setenv("SDSS_USER", "envuser")
    monkeypatch.setenv("SDSS_PASSWORD", "envpw")
    got = resolve(
        "data.sdss5.org", username="explicit", password="p", netrc_path=netrc_file
    )
    assert got.username == "explicit"


def test_environment_beats_netrc(monkeypatch, netrc_file):
    monkeypatch.setenv("SDSS_USER", "envuser")
    monkeypatch.setenv("SDSS_PASSWORD", "envpw")
    assert resolve("data.sdss5.org", netrc_path=netrc_file).username == "envuser"


def test_netrc_is_used_when_nothing_else_is_set(netrc_file):
    got = resolve("data.sdss5.org", netrc_path=netrc_file)
    assert (got.username, got.password) == ("netrcuser", "netrcpw")


def test_netrc_miss_for_a_different_host(netrc_file):
    with pytest.raises(AuthError):
        resolve("example.org", netrc_path=netrc_file)


def test_partial_environment_is_ignored(monkeypatch, netrc_file):
    monkeypatch.setenv("SDSS_USER", "envuser")  # no password
    assert resolve("data.sdss5.org", netrc_path=netrc_file).username == "netrcuser"


def test_missing_credentials_raise_an_actionable_error(tmp_path):
    with pytest.raises(AuthError) as excinfo:
        resolve("data.sdss5.org", netrc_path=tmp_path / "absent")
    message = str(excinfo.value)
    assert "machine data.sdss5.org" in message
    assert "SDSS_USER" in message


def test_optional_resolution_returns_none(tmp_path):
    got = resolve("data.sdss5.org", netrc_path=tmp_path / "absent", required=False)
    assert got is None


def test_world_readable_netrc_warns(netrc_file):
    netrc_file.chmod(0o644)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolve("data.sdss5.org", netrc_path=netrc_file)
    assert any("chmod 600" in str(w.message) for w in caught)


def test_prompting_is_never_implicit(tmp_path, monkeypatch):
    """A library must not block on input() in a batch job."""
    def explode(*_args, **_kwargs):
        raise AssertionError("prompted without allow_prompt")

    monkeypatch.setattr("builtins.input", explode)
    with pytest.raises(AuthError):
        resolve("data.sdss5.org", netrc_path=tmp_path / "absent")


def test_prompt_skipped_without_a_tty(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(AuthError):
        resolve("data.sdss5.org", netrc_path=tmp_path / "absent", allow_prompt=True)


# ----------------------------------------------------------------------
# credentials must not leak
# ----------------------------------------------------------------------


def test_password_is_hidden_from_repr_and_str():
    creds = Credentials("someuser", "hunter2")
    assert "hunter2" not in repr(creds)
    assert "hunter2" not in str(creds)
    assert "someuser" in repr(creds)


def test_credentials_become_fsspec_storage_options():
    options = Credentials("someuser", "pw").as_storage_options()
    header = options["client_kwargs"]["headers"]["Authorization"]
    assert header.startswith("Basic ")
    import base64
    assert base64.b64decode(header.split()[1]).decode() == "someuser:pw"


# ----------------------------------------------------------------------
# wiring into Access
# ----------------------------------------------------------------------


def test_public_release_needs_no_credentials():
    from sloppy_sdss_access import SDSS, Access

    assert Access(SDSS("dr19")).credentials is None


def test_collaboration_release_demands_credentials(tmp_path):
    from sloppy_sdss_access import SDSS, Access

    access = Access(SDSS("sdsswork"), netrc_path=tmp_path / "absent")
    with pytest.raises(AuthError):
        _ = access.credentials


def test_access_injects_auth_into_storage_options():
    from sloppy_sdss_access import SDSS, Access

    access = Access(SDSS("sdsswork"), username="u", password="p")
    assert "Authorization" in access._options["client_kwargs"]["headers"]


def test_credentials_are_resolved_once(monkeypatch):
    from sloppy_sdss_access import SDSS, Access

    access = Access(SDSS("sdsswork"), username="u", password="p")
    first = access.credentials
    assert access.credentials is first


def test_local_protocol_skips_auth_entirely():
    from sloppy_sdss_access import SDSS, Access

    assert Access(SDSS("sdsswork"), protocol="file").credentials is None


# ----------------------------------------------------------------------
# compression probing (sdss/sdss_access#66)
# ----------------------------------------------------------------------


def test_uri_variants_add_compression_suffixes():
    from sloppy_sdss_access import SDSS, Access

    a = Access(SDSS("dr19"))
    variants = a._variants("https://host/x.fits")
    assert variants[0] == "https://host/x.fits"
    assert "https://host/x.fits.gz" in variants


def test_already_compressed_template_never_probes(monkeypatch):
    """dr19's astraAllStarASPCAP is templated '.fits.gz' -- nothing to discover."""
    from sloppy_sdss_access import SDSS, Access

    dr19 = SDSS("dr19")
    assert dr19.product("astraAllStarASPCAP").compression == ".gz"
    assert not dr19.product("astraAllStarASPCAP").may_be_compressed

    a = Access(dr19)

    class Boom:
        def exists(self, uri):
            raise AssertionError("probed an already-compressed template")

    monkeypatch.setattr(type(a), "fs", property(lambda self: Boom()))
    assert a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0") == a.uri(
        "astraAllStarASPCAP", v_astra="0.6.0"
    )


def test_never_compressed_extension_does_not_probe(monkeypatch):
    """A .png or .parquet is never gzipped, so don't spend a request on it."""
    from sloppy_sdss_access import SDSS, Access

    work = SDSS("sdsswork")
    png = next(
        s for s in work
        if work.product(s).template.endswith(".png") and not work.product(s).broken
    )
    assert not work.product(png).may_be_compressed


def test_probe_is_learned_once_per_species(monkeypatch):
    """Looping over 10,000 stars must cost one probe, not 10,000."""
    from sloppy_sdss_access import SDSS, Access

    a = Access(SDSS("sdsswork"), username="u", password="p")
    calls = []

    class CountingFS:
        def exists(self, uri):
            calls.append(uri)
            return uri.endswith(".fits")  # template is already right

    monkeypatch.setattr(type(a), "fs", property(lambda self: CountingFS()))
    for sdss_id in range(100):
        a.resolve_uri("mwmStar", v_astra="0.6.0", sdss_id=87640000 + sdss_id)
    assert len(calls) == 1, f"probed {len(calls)} times for 100 files"


def test_resolve_uri_picks_the_variant_that_exists(monkeypatch):
    """sdsswork templates astraAllStarASPCAP '.fits'; the SAS stores '.fits.gz'."""
    from sloppy_sdss_access import SDSS, Access

    a = Access(SDSS("sdsswork"), username="u", password="p")
    real = a.uri("astraAllStarASPCAP", v_astra="0.6.0") + ".gz"

    class FakeFS:
        def exists(self, uri):
            return uri == real

    monkeypatch.setattr(type(a), "fs", property(lambda self: FakeFS()))
    assert a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0") == real


def test_probe_compression_can_be_disabled(monkeypatch):
    from sloppy_sdss_access import SDSS, Access

    a = Access(SDSS("sdsswork"), username="u", password="p", probe_compression=False)

    class Boom:
        def exists(self, uri):
            raise AssertionError("probed despite probe_compression=False")

    monkeypatch.setattr(type(a), "fs", property(lambda self: Boom()))
    assert a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0") == a.uri(
        "astraAllStarASPCAP", v_astra="0.6.0"
    )
