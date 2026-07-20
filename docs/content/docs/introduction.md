---
title: Introduction
weight: 1
---

# Introduction

`sloppy-sdss-access` resolves paths to SDSS data products. It covers **13 releases** —
SDSS-5 (`sdsswork`, `ipl1`–`ipl4`, `dr18`–`dr20`) and SDSS-4 (`dr13`–`dr17`) —
across **3,712 product definitions**.

It exists to test one idea: that path resolution does not need environment variables.

## The core idea

Every `$ENVVAR` in a `tree` path template is itself defined *inside the same tree
config file*, as `%(...)s` interpolations rooted at `FILESYSTEM`. Nothing about them
is a property of your machine. So they can all be resolved **once, at build time**,
and each template stored as a plain path relative to the SAS root.

A template that starts life in `tree` looking like this:

```ini
specLite = $BOSS_SPECTRO_REDUX/{run2d}/spectra/lite/@pad_fieldid|@isplate|/{mjd}/spec-@pad_fieldid|-{mjd}-{catalogid}.fits
```

is compiled to this, with `$BOSS_SPECTRO_REDUX` already expanded:

```
dr19/spectro/boss/redux/{run2d}/spectra/lite/@pad_fieldid|@isplate|/{mjd}/spec-@pad_fieldid|-{mjd}-{catalogid}.fits
```

That single change removes the need for environment variables entirely. The runtime
does `str.format()` plus a handful of pure functions, and nothing else.

> [!INFO]
> The compilation step is [`sloppy-sdss-access-build-registry`]({{< relref "/docs/registry" >}}).
> It is an *offline build step*, not a runtime dependency — the shipped package
> contains only the compiled `registry.json`.

## What that buys

### Nothing is written to your environment

Constructing a legacy `Path` replants the tree and overwrites the process
environment. Measured on a clean interpreter:

```python
import os
before = set(os.environ)
from sloppy_sdss_access import Path
Path(release="dr19")
print("added", len(set(os.environ) - before))
```

| package | variables added |
|---|---|
| `sdss-access` 3.0.11 | **97** |
| `sloppy-sdss-access` | **0** |

Legacy also `makedirs`-es your `$SAS_BASE_DIR` as a side effect of construction.
This package creates nothing and writes nothing.

### Two releases coexist

Because `SDSS` is a frozen dataclass carrying its own registry, and nothing lives
in a global, holding two releases at once is unremarkable:

```python
from sloppy_sdss_access import SDSS
dr18, dr19 = SDSS("dr18"), SDSS("dr19")
print(len(dr18), len(dr19))
```

```
96 334
```

This is [sdss/sdss_access#34](https://github.com/sdss/sdss_access/issues/34) and
[#97](https://github.com/sdss/sdss_access/issues/97). It is fixed *within* SDSS-5 and
SDSS-4. Mixing DR17 with DR12 still means running legacy `sdss_access` alongside,
which does replant the tree.

### Path resolution is faster

Measured with `timeit`, 5,000 iterations each, same machine, DR19:

| product | derivations | `sloppy-sdss-access` | `sdss-access` 3.0.11 | speedup |
|---|---|---|---|---|
| `astraAllStarASPCAP` | 0 | **0.58 µs** | 11.13 µs | 19× |
| `apStar` | 1 | **1.53 µs** | 57.02 µs | 37× |
| `specLite` | 2 | **2.56 µs** | 154.22 µs | 60× |

The gap widens with the number of derivations, because `sdss_access` AST-parses its
own special-function source code and stats the filesystem on *every* call. Here the
keys each derivation consumes are declared in a table at build time, so nothing is
re-discovered at runtime.

### Remote access is not a separate stack

`fsspec` handles `https`, `s3` and `file` behind one interface, which gets you
streaming range reads, genuinely concurrent downloads, and on-disk caching for free.
See [Remote access]({{< relref "/docs/remote-access" >}}).

## The comparison table

| | `sdss_access` | `sloppy-sdss-access` |
|---|---|---|
| env vars written to `os.environ` | +97 | **+0** |
| creates `$SAS_BASE_DIR` on import | yes | no |
| two releases in one session | mutate shared global state | independent frozen objects |
| dependencies for path resolution | `sdss-tree`, `requests`, `six`, … | **none** beyond the stdlib |
| transports | rsync, curl, http | anything `fsspec` speaks (https, s3, file, …) |
| missing required key | may emit a malformed path | raises `MissingKeys` |
| undefined `$VAR` in template | returns the literal `$VAR` | raises `UnresolvableProduct` |
| release-implied versions | no | yes (DR19 only, so far) |
| async / concurrent download | no | yes |
| streaming without download | no | yes |
| releases | DR7–DR19 | DR13–DR20, `sdsswork`, `ipl1`–`ipl4` |

## When *not* to use this

> [!WARNING]
> **Use the original `sdss_access` if you need any of the following.**
>
> * **DR7–DR12** (SDSS-I/II/III). Not available here. `SDSS("dr12")` raises at
>   construction. These releases are inherited *from* by the DR13+ configs, but are
>   not offered as releases in their own right.
> * **Software-product paths.** Templates rooted at `$PRODUCT_ROOT`, `$PLATELIST_DIR`,
>   `$MANGACORE_DIR` and friends point at svn/git checkouts on *your* machine, not at
>   archive data. They are marked `external` here and cannot be compiled.
>   See [Releases]({{< relref "/docs/releases#the-product_root-problem" >}}).
> * **The rsync or curl transports specifically** — a mirrored `rsync://` tree, or a
>   site where HTTPS is blocked. `RsyncAccess` and `CurlAccess` raise
>   `NotImplementedError`. This is *not* a lack of remote access: downloads work,
>   over HTTPS via `fsspec`. See below.
> * **A production guarantee.** This is a prototype. Read
>   [Limitations]({{< relref "/docs/limitations" >}}) first.

Remote access is fully supported — it simply uses a different transport. `Access`
downloads over HTTPS, concurrently, with streaming and caching that the legacy rsync
and curl paths never had:

```python
from sloppy_sdss_access import SDSS, Access

a = Access(SDSS("dr19"))

a.fetch("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)  # one file
a.fetch_many([("specLite", keys), ...], concurrency=8)                # concurrent
a.open("astraAllStarASPCAP")                                          # stream, no download
```

The legacy `add()` / `set_stream()` / `commit()` batching model maps onto
`fetch_many()`. See [Remote access]({{< relref "/docs/remote-access" >}}) and
[Migrating]({{< relref "/docs/migrating" >}}).

## Verification

Nothing here is asserted without a differential check. `tools/parity_check.py`
resolves every product in every release with **both** implementations, under five key
scenarios each:

```
  TOTAL: legacy unresolved=275  match=16820  skipped=293

  Derivation coverage: 18/24 exercised
    every derivation ran and produced >=2 distinct outputs

  RESULT: PASS
```

**16,820 comparisons, zero divergences.** The `skipped` are `external` products and
products whose templates reference undefined variables — neither implementation can
resolve them, so they are excluded rather than counted as passes. The 275
`legacy unresolved` are cases where the old package returned a literal `$VAR`;
see [Migrating]({{< relref "/docs/migrating#bugs-this-surfaced" >}}).
