#!/usr/bin/env python
"""Shim. The builder lives in the package so it can ship as a console script.

    sloppy-sdss-access-build-registry --fetch

is equivalent to running this file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sloppy_sdss_access._build import main  # noqa: E402

if __name__ == "__main__":
    main()
