---
title: Quickstart
weight: 3
---

# Quickstart

Every output on this page was produced by running the code shown.

## Install

```bash
uv add sloppy-sdss-access
```

## Resolve a path

```python
from sloppy_sdss_access import SDSS

dr19 = SDSS("dr19")
dr19.path("astraAllStarASPCAP")
```

```
'dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'
```

No `$SAS_BASE_DIR`, no `~/.netrc`, no module files. `path()` returns a path
**relative to the SAS root**, which is the form that is identical for every user.

> [!INFO]
> Notice that you did not supply `v_astra=0.6.0`. DR19 knows its own pipeline
> versions — see [release defaults](#release-defaults) below.

## The three flavours of location

```python
dr19.path("specLite",  fieldid=15000, mjd=59146, catalogid=4375924756)
dr19.url("specLite",   fieldid=15000, mjd=59146, catalogid=4375924756)
dr19.local("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

```
'dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'https://data.sdss.org/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
PosixPath('/Users/acasey/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits')
```

| method | returns | needs a local root? |
|---|---|---|
| `path()` | SAS-relative path | no |
| `url()` | full `https://` URL | no |
| `local()` | `pathlib.Path` under your SAS root | **yes** |

`local()` takes the first of `SDSS(root=...)`, then `$SAS_BASE_DIR` if set
(read-only), then `~/sas`:

```python
SDSS("dr19", root="/data/sas").local("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

```
PosixPath('/data/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits')
```

## Explore what a release contains

```python
from sloppy_sdss_access import SDSS, known_releases

known_releases()
```

```
('dr13', 'dr14', 'dr15', 'dr16', 'dr17', 'dr18', 'dr19', 'dr20', 'ipl1', 'ipl2', 'ipl3', 'ipl4', 'sdsswork')
```

```python
dr19 = SDSS("dr19")
repr(dr19)
len(dr19)
"apStar" in dr19
```

```
"SDSS(release='dr19', products=334, public, date=2025-07-10)"
334
True
```

Glob the product list:

```python
dr19.search("mwm*")
```

```
['mwmAllStar', 'mwmAllVisit', 'mwmStar', 'mwmTargets', 'mwmVisit']
```

Ask what keys a product takes:

```python
dr19.keys("mwmStar")
```

```
('sdss_id', 'v_astra')
```

And get the whole picture:

```python
print(dr19.describe("specFull"))
```

```
specFull (dr19)
  template : dr19/spectro/boss/redux/{run2d}/spectra/full/@pad_fieldid|@isplate|/{mjd}/spec-@pad_fieldid|-{mjd}-{catalogid}.fits
  required : catalogid, fieldid, mjd, run2d
  optional : -
  derived  : isplate, pad_fieldid
  compress : maybe
```

## Release defaults

```python
dr19.defaults
```

```
{'run2d': 'v6_1_3', 'apred': '1.4', 'v_astra': '0.6.0'}
```

These are merged in before your keys, so you can omit them — and override them
when you need to.

> [!WARNING]
> **Only DR19 is seeded.** Every other release returns `{}` and you must pass the
> pipeline versions yourself. See [Limitations]({{< relref "/docs/limitations" >}}).

## Errors are loud

```python
dr19.path("specFull", mjd=59797, catalogid=1)
```

```
MissingKeys: "'specFull' requires fieldid. Full key set: catalogid, fieldid, mjd, run2d."
```

```python
dr19.path("nosuchthing")
```

```
UnknownProduct: "'nosuchthing' is not in release 'dr19'."
```

The legacy package would have returned `dr19/.../spec--59797-1.fits` for the first
of those — a malformed filename with an empty segment. See
[Migrating]({{< relref "/docs/migrating" >}}).

## Two releases at once

```python
dr18, dr19 = SDSS("dr18"), SDSS("dr19")
print(len(dr18), len(dr19))
```

```
96 334
```

`SDSS` is a frozen dataclass carrying its own registry. Nothing is global, so there
is no interference.

## Fetch data

```python
from sloppy_sdss_access import SDSS, Access

a = Access(SDSS("dr19"))
a.exists("astraAllStarASPCAP")
a.size("astraAllStarASPCAP")
```

```
True
1171102556
```

Stream a header from that 1.17 GB file without downloading it:

```python
with a.open("astraAllStarASPCAP") as fp:
    head = fp.read(64)
print(head[:4].hex(), head[:2] == b"\x1f\x8b")
```

```
1f8b0808 True
```

Download concurrently, with an on-disk cache:

```python
import time
items = [("specLite", dict(fieldid=15000, mjd=59146, catalogid=4375924756))]

t = time.time(); a.fetch_many(items); print("%.1fs" % (time.time() - t))
t = time.time(); a.fetch_many(items); print("%.4fs" % (time.time() - t))
```

```
1.4s
0.0004s
```

The second call is served from `~/.cache/sdss_access`.

> [!DANGER]
> **The cache has no eviction policy.** It grows without bound. See
> [Remote access]({{< relref "/docs/remote-access#caching" >}}).

## Where next

* [**Migrating from `sdss_access`**]({{< relref "/docs/migrating" >}}) — if you have existing code
* [Path resolution]({{< relref "/docs/path-resolution" >}}) — templates, keys, derivations
* [Remote access]({{< relref "/docs/remote-access" >}}) — streaming, async, compression probing
* [Authentication]({{< relref "/docs/authentication" >}}) — collaboration data
* [Limitations]({{< relref "/docs/limitations" >}}) — what does not work
