"""SDSS data product paths, without the environment variables.

A prototype replacement for ``sdss_access``, covering SDSS-5 (``sdsswork``,
``ipl1``-``ipl4``, ``dr18``-``dr20``) and SDSS-4 (``dr13``-``dr17``)::

    from sloppy_sdss_access import SDSS, Access

    dr19 = SDSS("dr19")
    dr19.path("astraAllStarASPCAP")          # release defaults fill in the versions
    dr19.url("specFull", fieldid=101077, mjd=59797, catalogid=27021598108587618)

    Access(dr19).fetch("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)

DR7-DR12 (SDSS-I/II/III) are inherited from by the DR13+ configs but are not
offered as releases.

The distribution is ``sloppy-sdss-access`` but the importable module is
``sdss_access``, so existing code keeps importing::

    from sloppy_sdss_access import Path      # legacy-shaped shim, see sloppy_sdss_access.compat

WARNING: installing this **shadows the real** ``sdss-access``. The two cannot
coexist in one environment. If you need DR7-DR12, keep the original in a
separate environment.
"""

from .access import Access
from .auth import AuthError, Credentials
from .compat import AccessError, CurlAccess, HttpAccess, Path, RsyncAccess, SDSSPath
from .paths import (
    MissingKeys,
    SDSS,
    UnknownProduct,
    UnresolvableProduct,
    known_releases,
)
from .registry import Product, Release, load, releases

__version__ = "0.1.0"

__all__ = [
    "SDSS",
    "Access",
    # Legacy-compatible names, so `from sloppy_sdss_access import Path` keeps working.
    # See sloppy_sdss_access.compat for exactly how far the compatibility goes.
    "Path",
    "SDSSPath",
    "AccessError",
    "HttpAccess",
    "RsyncAccess",
    "CurlAccess",
    "AuthError",
    "Credentials",
    "Product",
    "Release",
    "MissingKeys",
    "UnknownProduct",
    "UnresolvableProduct",
    "known_releases",
    "load",
    "releases",
    "__version__",
]
