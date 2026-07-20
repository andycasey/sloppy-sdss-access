---
title: sloppy-sdss-access
type: docs
bookToc: false
---

# sloppy-sdss-access

**SDSS data product paths, without the environment variables.**

A prototype replacement for `sdss_access`. It resolves every
`$ENVVAR` in the [`sdss/tree`](https://github.com/sdss/tree) config files **once, at build
time**, and ships the result as a static registry. The runtime then needs no
environment variables at all.

```python
from sloppy_sdss_access import SDSS

dr19 = SDSS("dr19")

dr19.path("astraAllStarASPCAP")
# 'dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'

dr19.url("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
# 'https://data.sdss.org/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
```


## Start here

{{% columns %}}

- ### New to this package

  1. [Introduction]({{< relref "/docs/introduction" >}}) — what it is and why
  2. [Installation]({{< relref "/docs/installation" >}})
  3. [Quickstart]({{< relref "/docs/quickstart" >}}) — the ten-minute tour

- ### Coming from `sdss_access`

  1. [**Migrating from `sdss_access`**]({{< relref "/docs/migrating" >}}) — the key page
  2. [Path resolution]({{< relref "/docs/path-resolution" >}}) — templates and keys
  3. [Limitations]({{< relref "/docs/limitations" >}}) — read before you rely on it

{{% /columns %}}

---

## At a glance

| | `sdss_access` | `sloppy-sdss-access` |
|---|---|---|
| env vars written to `os.environ` | **+97** | **+0** |
| two releases in one session | mutate shared global state | independent frozen objects |
| dependencies for path resolution | `sdss-tree`, `requests`, `six`, … | **none** beyond the stdlib |
| transports | rsync, curl, http | anything `fsspec` speaks |
| releases covered | DR7–DR19 | **13**: DR13–DR20, `sdsswork`, `ipl1`–`ipl4` |

> **This is a prototype, not a finished package.** Several things are unimplemented,
> untested, or deliberately incomplete. The [Limitations]({{< relref "/docs/limitations" >}})
> page lists them without softening.
