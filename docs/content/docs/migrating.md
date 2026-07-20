---
title: Migrating from sdss_access
weight: 4
---

# Migrating from `sdss_access`

**Porting is a one-line import change.** Swap `from sdss_access import Path` for
`from sloppy_sdss_access import Path` — the legacy names (`Path`, `SDSSPath`,
`RsyncAccess`, `AccessError`, …) are re-exported unchanged, and `full()`,
`location()` and `url()` were verified **byte-identical** against the real package.
`tests/test_compat.py` pins the reference values.

> Only the import line changes; everything after it stays the same. See below.

## Side by side

| legacy | here |
|---|---|
| `Path(release="dr19")` | same, or `SDSS("dr19")` for the native API |
| `SDSSPath(...)` | same — `SDSSPath is Path` |
| `.full(sp, **k)` | same — absolute, under `root=` / `$SAS_BASE_DIR` / `~/sas` |
| `.location(sp, **k)` | same — or native `SDSS.path()` |
| `.url(sp, **k)` | same, including the `data.sdss.org` vs `data.sdss5.org` split |
| `.name(sp, **k)` | same |
| `.dir(sp, **k)` | same |
| `.exists(sp, **k)` | same — local check; `remote=True` goes over fsspec |
| `.templates` | same — `{species: template}` |
| `.lookup_keys(sp)` / `.lookup_names()` / `.has_name(sp)` | same |
| `AccessError` | same — retained so `except AccessError` keeps compiling |
| `HttpAccess().get(sp, **k)` | `Access(SDSS(r)).fetch(sp, **k)` |
| `RsyncAccess().add(); .set_stream(); .commit()` | `Access(SDSS(r)).fetch_many([(sp, keys), ...])` |
| `CurlAccess()` | **removed** — raises `NotImplementedError` |
| `Auth` / `set_auth(inquire=True)` | `sloppy_sdss_access.auth` — never prompts unless asked |
| `Tree`, `check_modules()`, `force_modules` | **gone** — there is no tree to plant |

> [!INFO]
> **`SDSS` vs `Path`.** `SDSS` is the native API (`.path()`, `.local()`, `.url()`);
> `Path` is the legacy-shaped shim (`.location()`, `.full()`, `.url()`). They resolve
> identically — `Path` just delegates. New code should use `SDSS`.

## The shim in practice

```python
from sloppy_sdss_access import Path, SDSSPath

SPEC = dict(fieldid=15000, mjd=59146, catalogid=4375924756, run2d="v6_1_3")
p = Path(release="dr19", root="/tmp/sas")

p.full("specLite", **SPEC)
p.location("specLite", **SPEC)
p.url("specLite", **SPEC)
p.name("specLite", **SPEC)
p.dir("specLite", **SPEC)
SDSSPath is Path
```

```
'/tmp/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'https://data.sdss.org/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'spec-015000-59146-4375924756.fits'
'/tmp/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146'
True
```

The same query against the **real `sdss-access` 3.0.11**, run in a separate
virtualenv:

```bash
$ SAS_BASE_DIR=/tmp/sas python -c "
from sloppy_sdss_access import Path
p = Path(release='dr19')
print(p.location('specLite', fieldid=15000, mjd=59146, catalogid=4375924756, run2d='v6_1_3'))
print(p.url('specLite', fieldid=15000, mjd=59146, catalogid=4375924756, run2d='v6_1_3'))"
```

```
dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits
https://data.sdss.org/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits
```

Identical.

### Dead arguments are accepted and ignored

`verbose`, `public`, `force_modules`, `preserve_envvars` no longer mean anything —
there is no global environment to preserve, and access is decided by HTTP auth
rather than by URL. They are accepted so existing call sites do not break:

```python
Path(release="dr19", public=True, verbose=True,
     force_modules=True, preserve_envvars=True)
```

Likewise the per-call control kwargs `force_module`, `skip_tag_check`, `remote` and
`full` are stripped before key substitution.

---

## Deliberately different

These are the behaviour changes you should actually plan for. None of them are
accidents.

### 1. Missing keys raise

Legacy could emit a **malformed path with an empty segment**. Verified against
`sdss-access` 3.0.11:

```bash
$ python -c "
from sloppy_sdss_access import Path
print(Path(release='dr19').location('specFull', fieldid='', mjd=59797, catalogid=1, run2d='v6_1_3'))"
```

```
dr19/spectro/boss/redux/v6_1_3/spectra/full/59797/spec--59797-1.fits
```

Note `spec--59797-1.fits` — a double hyphen where the field ID should be. Here:

```python
SDSS("dr19").path("specFull", mjd=59797, catalogid=1)
```

```
MissingKeys: "'specFull' requires fieldid. Full key set: catalogid, fieldid, mjd, run2d."
```

> [!WARNING]
> **Migration impact.** Code that relied on a blank key producing *something* will now
> raise. This is almost always a latent bug being surfaced, but it will surface at
> import-and-run time rather than when someone notices the filename is wrong.

### 2. Undefined variables raise

37 SDSS-5 product definitions reference environment variables their own release
never defines. `sdss_access` uses `os.path.expandvars`, which leaves unknown
variables untouched:

```python
Path(release="dr17").full("portsmouth_emlinekin", galaxy_vers="v1", run2d="v5_13_2")
```

```
'$BOSS_GALAXY_REDUX/v1/portsmouth_emlinekin-v5_13_2.fits'
```

A path with a literal `$VAR` in it, returned without complaint. Here the same query
resolves properly, because this build overrides per *variable* rather than deleting
a whole config section (see [Releases]({{< relref "/docs/releases#the-bosseboss-section-deletion" >}})):

```python
SDSS("dr17").path("portsmouth_emlinekin", galaxy_vers="v1", run2d="v5_13_2")
```

```
'dr17/eboss/spectro/redux/galaxy/v1/portsmouth_emlinekin-v5_13_2.fits'
```

Where no correct answer exists, this package refuses rather than guessing:

```python
SDSS("dr19").path("asR", mjd=59797, chip="a", num=1)
```

```
UnresolvableProduct: 'asR' in 'dr19' references $APOGEE_DATA_S, which this release
never defines. This is a defect in the upstream tree config; sdss_access silently
returns a path with the literal variable in it.
```

### 3. Release defaults make `run2d` optional

```python
Path("dr19").location("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

```
'dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
```

Legacy raised `KeyError` for the missing `run2d`. DR19 now implies `v6_1_3`.
**Only DR19 is seeded** — see [Path resolution]({{< relref "/docs/path-resolution#release-defaults" >}}).

### 4. No `os.environ` writes

Constructing a legacy `Path` replants the tree and overwrites the environment.
Measured on a clean interpreter:

```python
import os
before = set(os.environ)
from sloppy_sdss_access import Path
Path(release="dr19")
print("added", len(set(os.environ) - before))
```

| package | added |
|---|---|
| `sdss-access` 3.0.11 | `added 97` |
| `sloppy-sdss-access` | `added 0` |

The 97 include `APOGEE_DATA_S`, `ALLWISE_DIR`, `APOGEE_ASPCAP`, … Legacy also
`makedirs`-es your `$SAS_BASE_DIR` as a side effect of construction. This package
creates nothing.

> [!WARNING]
> **This is not a cosmetic difference.** Because the tree is global, legacy
> `Path(release="dr19")` can leak *another* release's roots into your resolution.
> Verified on a clean interpreter with `sdss-access` 3.0.11:
>
> ```python
> Path(release="dr19").location("asR", mjd=59797, chip="a", num=1)
> # 'sdsswork/data/apogee/lco/59797/asR-a-00000001.apz'
> ```
>
> A **`dr19`** query returning an **`sdsswork`** path, because `$APOGEE_DATA_S` was
> planted from a different config. This package raises `UnresolvableProduct` instead.

### 5. No rsync or curl

```python
from sloppy_sdss_access import RsyncAccess
RsyncAccess()
```

```
NotImplementedError: RsyncAccess is not provided by sloppy-sdss-access. There is no rsync
transport; downloads go over HTTPS via fsspec, and the add()/set_stream()/commit()
batching model is replaced by fetch_many().
Use:  from sloppy_sdss_access import SDSS, Access
      a = Access(SDSS('dr19'))
      a.fetch(species, **keys)                 # one file
      a.fetch_many([(species, keys), ...])     # concurrent
      a.open(species, **keys)                  # stream, no download
```

The batching model translates directly:

```python
# legacy
rsync = RsyncAccess(release="dr19")
rsync.remote()
rsync.add("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
rsync.add("specLite", fieldid=15000, mjd=59146, catalogid=4375924757)
rsync.set_stream()
rsync.commit()

# here
from sloppy_sdss_access import SDSS, Access
a = Access(SDSS("dr19"))
a.fetch_many([
    ("specLite", dict(fieldid=15000, mjd=59146, catalogid=4375924756)),
    ("specLite", dict(fieldid=15000, mjd=59146, catalogid=4375924757)),
])
```

`fetch_many` returns a list of `pathlib.Path` positionally aligned with the input.
See [Remote access]({{< relref "/docs/remote-access" >}}).

### 6. DR7–DR12 unavailable

```python
Path(release="dr12")
```

```
KeyError: "'dr12' is not an SDSS-5 release. Known releases: dr13, dr14, dr15, dr16,
dr17, dr18, dr19, dr20, ipl1, ipl2, ipl3, ipl4, sdsswork. DR7-DR12 (SDSS-I/II/III)
are handled by the legacy sdss_access."
```

It raises **at construction**, as legacy validated the release at construction.
DR7–DR12 are inherited *from* by the DR13+ configs but are not offered as releases.
Keep the original `sdss_access` in a separate environment for these.

---

## How the equivalence was checked

`tools/parity_check.py` resolves **every product in every release** with both
implementations, under five key scenarios each, and diffs the results:

```
  ipl2       match=535
  ipl3       match=940  skipped=27
  ipl4       match=1005  skipped=27
  sdsswork   match=2225  skipped=18
  dr13       legacy unresolved=55  match=1355  skipped=34
  dr14       legacy unresolved=55  match=1365  skipped=34
  dr15       legacy unresolved=55  match=1410  skipped=34
  dr16       legacy unresolved=55  match=1630  skipped=36
  dr17       legacy unresolved=55  match=1865  skipped=36

  TOTAL: legacy unresolved=275  match=16820  skipped=293

  Derivation coverage: 18/24 exercised
    every derivation ran and produced >=2 distinct outputs

  RESULT: PASS
```

**16,820 comparisons, zero divergences.**

* `skipped` — `external` products and products whose templates reference undefined
  variables. Neither implementation can resolve them, so they are excluded rather
  than counted as passes.
* `legacy unresolved` — 275 resolutions across 55 products where the old package
  returned a literal `$VAR`. These are the `portsmouth_*` / `granada_fsps*` /
  `wisconsin_pca*` VACs; see [Releases]({{< relref "/docs/releases#the-bosseboss-section-deletion" >}}).

### The coverage gate

An earlier version of the harness pinned `run2d="v6_1_3"`, which makes every
reorganised-BOSS-layout branch dead code. Ten derivations then returned a single
constant, and five were never called — half of `derive.py` could have been replaced
with hardcoded strings and the check would still have passed.

The scenarios now vary `run2d`, `telescope`, `obs`, `ftype` and numeric magnitude,
and the run **fails** unless every derivation is exercised with **≥2 distinct
outputs**. Mutation-tested: replacing `pad_fieldid`, `spcoaddobs`, `sptypefolder` or
`healpixgrp` with a constant is caught.

Three derivations (`configgrp`, `configsubmodule`, `platedir`) are reachable only
from `external` products, so parity cannot cover them. They are unit-tested and
explicitly exempted from the gate rather than silently counted.

> [!WARNING]
> **Known blind spot.** The comparison normalises away `.gz`/`.bz2`/`.zip`/`.fz`
> suffixes, because legacy probes the local filesystem and nothing exists locally. So
> parity says **nothing** about compressed-file resolution
> ([#66](https://github.com/sdss/sdss_access/issues/66)) — that is verified separately
> against the live SAS. See [Remote access]({{< relref "/docs/remote-access#compression-probing" >}}).

To run it yourself you need the legacy package in its own virtualenv:

```bash
pip install sdss-access     # for the differential parity check
python tools/parity_check.py
```

---

## Bugs this surfaced

Two defects in the current stack, worth filing against `tree`/`sdss_access`
regardless of this prototype's fate.

### 1. Templates referencing undefined variables

37 SDSS-5 product definitions (and 55 more in SDSS-4) name environment variables
their own release chain never defines. Because `os.path.expandvars` leaves unknown
variables untouched, these silently return a path with a literal `$VAR` in it — or,
worse, a path from a *different release* if some other config happened to plant the
variable.

Affected in SDSS-5: `asR`, `cannonStar`, `cannonStar-1m`, `apogee-rc`
(`dr19`/`dr20`/`sdsswork`), `gcam_lco` (`dr20`), and the `aspcap*`/`apogee*` family
in `ipl3`/`ipl4`. The full list is printed by `sloppy-sdss-access-build-registry`.

Per-release counts measured from the registry:

| release | products marked `broken` |
|---|---|
| `dr16`, `dr17` | 2 each |
| `dr19` | 4 |
| `dr20` | 5 |
| `ipl3` | 13 |
| `ipl4` | 12 |
| `sdsswork` | 3 |

### 2. Dead branch in `spcoaddobs`

Upstream reads:

```python
if (('v5' in run2d) or ... or (...) and obs.lower()) == 'apo':
```

`== 'apo'` binds to the **whole parenthesised expression**, so this compares a `bool`
to a string and is always `False`. The APO-suppression it intends never happens.

Reproduced bug-for-bug in `derive.py` (marked `BUG-COMPAT`) so that parity holds. It
should be fixed in both places together.
