#!/usr/bin/env python
"""Shim. The builder lives in the package so it can ship as a console script.

    sloppy-sdss-access-build-registry --fetch

is equivalent to running this file.

``_build`` is loaded straight off disk rather than as ``sloppy_sdss_access._build``,
because importing it by package path would execute the package ``__init__``, which
imports ``fsspec`` -- and this script has to run in a bare checkout with nothing
installed (the registry poll in .github/workflows/update-registry.yml does exactly
that, on a runner with no dependencies). ``_build`` itself imports nothing outside
the standard library, so loading it directly costs nothing and needs nothing.
"""

import importlib.util
from pathlib import Path

_BUILD = Path(__file__).parent.parent / "src" / "sloppy_sdss_access" / "_build.py"

_spec = importlib.util.spec_from_file_location("sloppy_sdss_access_build", _BUILD)
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)

main = _build.main

if __name__ == "__main__":
    main()
