"""The build tooling: which tree tag to build from, and what version it earns.

No network -- `latest_tag()` shells out to `git ls-remote`, so the ordering it
depends on is tested against a fixed tag list instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sloppy_sdss_access import _build

REPO = Path(__file__).parent.parent


# ----------------------------------------------------------------------
# choosing a tree tag
# ----------------------------------------------------------------------

#: A slice of the real `git ls-remote --tags sdss/tree` output, unordered as it
#: arrives, including the older scheme that is not a candidate.
TREE_TAGS = ["4.0.8", "4.0.9", "4.0.10", "4.1.0", "4.1.4", "4.1.2",
             "v1_0", "v2_9", "v2_14"]


def test_newest_tag_orders_by_version_not_string():
    assert _build.newest_tag(TREE_TAGS) == "4.1.4"


def test_newest_tag_beats_string_order():
    """The bug this guards: "4.0.9" > "4.0.10" as strings."""
    assert _build.newest_tag(["4.0.9", "4.0.10"]) == "4.0.10"


def test_newest_tag_ignores_the_legacy_scheme():
    """tree's v2_14 is not comparable with 4.x and must never be chosen."""
    assert _build.newest_tag(["v2_14", "4.0.1"]) == "4.0.1"


def test_newest_tag_refuses_when_there_is_nothing_to_choose():
    with pytest.raises(SystemExit, match="pass --ref"):
        _build.newest_tag(["v2_14", "main"])


# ----------------------------------------------------------------------
# versioning
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "part,expected",
    [("major", "1.0.0"), ("minor", "0.2.0"), ("patch", "0.1.2"), ("", "0.1.1")],
)
def test_next_version(part, expected):
    assert _build.next_version("0.1.1", part) == expected


def test_next_version_rejects_nonsense():
    with pytest.raises(ValueError, match="not major, minor or patch"):
        _build.next_version("0.1.1", "megabump")


def test_bump_rewrites_every_file_that_carries_a_version(tmp_path, monkeypatch):
    """release.yml refuses to publish a tag that disagrees with either file."""
    import re

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "0.1.1"\n')
    init = tmp_path / "__init__.py"
    init.write_text('"""doc"""\n\n__version__ = "0.1.1"\n')

    monkeypatch.setattr(_build, "VERSION_FILES", (
        (pyproject, re.compile(r'^(version = ")([^"]+)(")', re.M)),
        (init, re.compile(r'^(__version__ = ")([^"]+)(")', re.M)),
    ))

    assert _build.bump("minor") == "0.2.0"
    assert 'version = "0.2.0"' in pyproject.read_text()
    assert '__version__ = "0.2.0"' in init.read_text()


def test_bump_refuses_when_the_files_already_disagree(tmp_path, monkeypatch):
    import re

    a = tmp_path / "pyproject.toml"
    a.write_text('version = "0.1.1"\n')
    b = tmp_path / "__init__.py"
    b.write_text('__version__ = "0.9.9"\n')
    monkeypatch.setattr(_build, "VERSION_FILES", (
        (a, re.compile(r'^(version = ")([^"]+)(")', re.M)),
        (b, re.compile(r'^(__version__ = ")([^"]+)(")', re.M)),
    ))

    with pytest.raises(SystemExit, match="disagree"):
        _build.bump("patch")


def test_the_shipped_version_files_agree():
    """The real ones, as bump() will find them."""
    found = set()
    for path, pattern in _build.VERSION_FILES:
        match = pattern.search(path.read_text())
        assert match, path
        found.add(match.group(2))
    assert len(found) == 1, found


# ----------------------------------------------------------------------
# running with nothing installed
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    not (REPO / "tools" / "build_registry.py").exists(),
    reason="needs a source checkout",
)
def test_the_shim_runs_without_the_runtime_dependencies(tmp_path):
    """The registry poll runs it on a bare runner, with nothing pip-installed.

    Regression test: the shim used to do `from sloppy_sdss_access._build import
    main`, which executes the package __init__ -- which imports fsspec. That is
    fine for the console script (an installed package has its dependencies) and
    fatal for a checkout that has none, which is exactly where CI runs it.
    """
    # A directory whose `fsspec` raises, placed first on the path: the same
    # failure a runner with no dependencies produces, without uninstalling.
    (tmp_path / "fsspec.py").write_text('raise ImportError("fsspec is not installed")\n')

    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "build_registry.py"), "--help"],
        capture_output=True, text=True, env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "--latest-tag" in proc.stdout

    # And prove the stand-in would really have broken the old import path.
    broken = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'src'); import sloppy_sdss_access"],
        capture_output=True, text=True, cwd=REPO,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert broken.returncode != 0 and "fsspec" in broken.stderr
