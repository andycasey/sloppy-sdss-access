---
title: Installation
weight: 2
---

# Installation

```bash
uv add sloppy-sdss-access
```

or, if you prefer pip:

```bash
pip install sloppy-sdss-access
```

Python **3.11 or newer** is required.

## The name you install is not the name you import

This trips everybody up once, so it is worth stating plainly:

| | name |
|---|---|
| **Distribution** (what you install) | `sloppy-sdss-access` |
| **Import package** (what you import) | `sloppy_sdss_access` |
| **Console script** | `sloppy-sdss-access-build-registry` |

The install name has hyphens; the import name has underscores — the usual Python
convention. There is **no** `sdss_access` module here; that is the *original*
package, which this one replaces.

```python
from sloppy_sdss_access import SDSS      # the native API
from sloppy_sdss_access import Path      # the legacy-shaped compatibility shim
```

Compatibility is at the level of *names*, not the module: the symbols the original
package exported — `Path`, `SDSSPath`, `RsyncAccess`, `AccessError`, … — are
re-exported from `sloppy_sdss_access` *deliberately*, so porting is a one-line import
change (`from sdss_access import Path` → `from sloppy_sdss_access import Path`) and
nothing after the import needs editing. See
[Migrating]({{< relref "/docs/migrating" >}}).


## Keeping a legacy environment alongside

If you need DR7–DR12, or you want to diff the two implementations, run the original
in its own virtualenv and drive it **out of process**. This is exactly what the
repository itself does:

```bash
# the new package
uv venv .venv
uv pip install --python .venv -e .

# the real sdss-access, isolated
pip install sdss-access     # for the differential parity check
```

Both packages coexist; the module names are distinct:

```bash
$ python -c "import sloppy_sdss_access, sdss_access
print(sloppy_sdss_access.__file__)
print(sdss_access.__file__)"
.../src/sloppy_sdss_access/__init__.py
.../site-packages/sdss_access/__init__.py
```

The differential test imports both:

```bash
python tools/parity_check.py
```

> [!INFO]
> **Why out of process, and not `importlib` tricks?** Because the legacy package
> mutates `os.environ` on import — 97 variables — and replants a global tree. Even if
> you could load both modules, the second one to construct a `Path` would corrupt the
> first one's view of the world. A subprocess is the honest boundary.

## Dependencies

Two are **required**:

```toml
dependencies = [
    "fsspec>=2024.6",
    "aiohttp>=3.9",
]
```

> [!INFO]
> `fsspec` and `aiohttp` are part of the baseline rather than an optional extra: a
> package whose point is fetching data should be able to fetch data straight after
> install.
>
> **Path resolution itself still imports nothing beyond the standard library.**
> `SDSS.path()` and `SDSS.url()` do not touch `fsspec`; it is only imported when you
> construct an `Access`.

## Extras

| extra | contents | use it for |
|---|---|---|
| `[s3]` | `s3fs>=2024.6` | `protocol="s3"` cloud buckets ([untested]({{< relref "/docs/limitations" >}})) |
| `[dev]` | `pytest>=8`, `pytest-asyncio>=0.23` | running the test suite |

```bash
uv add "sloppy-sdss-access[s3]"
uv add "sloppy-sdss-access[dev]"
```

## Verification

Confirm the install resolves a real path:

```python
from sloppy_sdss_access import SDSS
print(SDSS("dr19").path("astraAllStarASPCAP"))
```

```
dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz
```

Run the test suite from a checkout:

```bash
$ pytest -q
96 passed in 0.09s
```

And the differential check against the real `sdss-access` (install it alongside,
above):

```bash
$ python tools/parity_check.py
...
  TOTAL: legacy unresolved=275  match=16820  skipped=293

  Derivation coverage: 18/24 exercised
    every derivation ran and produced >=2 distinct outputs

  RESULT: PASS
```

## No configuration required

There is nothing to set up. No `$SAS_BASE_DIR`, no `~/.netrc`, no module files.

```python
from sloppy_sdss_access import SDSS
SDSS("dr19").url("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

works on a bare machine with an empty environment. Two exceptions, both narrow:

* **`local()`** needs a local SAS root. It takes the first of an explicit
  `SDSS(root=...)`, then `$SAS_BASE_DIR` if set (**read-only**, purely so an existing
  `sdss_access` machine works out of the box), then `~/sas`.
* **Collaboration data** needs credentials. Public DRs need none.
  See [Authentication]({{< relref "/docs/authentication" >}}).
