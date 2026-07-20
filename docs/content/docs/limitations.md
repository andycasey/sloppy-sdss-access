---
title: Limitations
weight: 10
---

# Limitations

> [!DANGER]
> **This is a prototype, not a package.** What follows is the honest list. Read it
> before building anything on top.

## Release defaults are seeded for DR19 only

```python
from sloppy_sdss_access import SDSS
SDSS("dr19").defaults     # {'run2d': 'v6_1_3', 'apred': '1.4', 'v_astra': '0.6.0'}
SDSS("dr20").defaults     # {}
SDSS("sdsswork").defaults # {}
```

The other **twelve** releases return `{}`. Their pipeline versions need to come from
the release coordinators; they are not in `tree`. Until then you must pass every
version key by hand on every release except DR19.

## S3 is untested

`Access(paths, protocol="s3", bucket=...)` constructs `s3://` URIs, and that much is
verified. Nothing else is:

* SDSS data is not on MAST yet, so **no bucket exists to check against**;
* **S3 credentials are not wired** — `Access.credentials` folds auth into
  `storage_options` only for `http`/`https`.

## No per-key default values

Only release-wide defaults exist. This is half of
[#100](https://github.com/sdss/sdss_access/issues/100): required-ness is declared per
product and enforced, but a product cannot say "if `component` is omitted, use `X`".

## `external` products cannot be resolved at all

Products rooted at software-checkout variables are marked `external` and raise
`UnresolvableProduct`, because there is no build-time value to substitute — the
location is a property of your machine, not of the archive:

```python
SDSS("dr17").path("plateHoles", plateid=8000)
```

```
UnresolvableProduct: 'plateHoles' is not archive data: its template is rooted at
$PRODUCT_ROOT, an svn/git software product checkout whose location is a property of
your machine, not of the SAS. ...
```

Detect them with `SDSS(r).product(sp).external` before calling `path()`.
Affected: 34 products per SDSS-4 release, 0–15 per SDSS-5 release (`ipl1` and `ipl2`
have none).

The proper fix is an explicit second resolver — `SDSS4(release=..., product_root=...)` —
so software-product paths are opt-in and obviously environment-dependent at the call
site. **Not implemented.** See [Releases]({{< relref "/docs/releases#the-product_root-problem" >}}).

## The registry is a build artifact of `tree`

Long term the templates should live somewhere versioned in their own right rather
than being scraped out of a config format designed for a different purpose. Every
upstream `tree` quirk — including the ones this project
[files bugs about]({{< relref "/docs/migrating#bugs-this-surfaced" >}}) — is inherited.

## `DERIVATION_KEYS` can drift from `derive.py`

The table declaring which keys each derivation consumes lives in the **builder**, not
next to the functions it describes. The two can silently disagree. A test catches
*unused* derivations, but **not wrong key sets**.

## Compression probing is a workaround

* It covers only the suffixes in `COMPRESSION_SUFFIXES` (`.gz`, `.bz2`, `.fz`,
  `.zip`, `.Z`).
* `NEVER_COMPRESSED` is a **hand-maintained** extension list.
* The correction is learned per species and cached on the `Access` instance, so a
  species that is genuinely inconsistent on the SAS will be resolved wrongly after
  the first probe.
* A failed probe is swallowed (`except Exception: continue`), so a network problem
  looks like "not compressed".

The underlying wrong templates should be fixed in `tree`. Probing is a workaround.

Note also that the **parity check cannot see this**: it normalises away compression
suffixes, because legacy probes the local filesystem and nothing exists locally. So
[#66](https://github.com/sdss/sdss_access/issues/66) is verified only against the
live SAS, by hand.

## No cache eviction

> [!DANGER]
> `~/.cache/sloppy_sdss_access` (or `$XDG_CACHE_HOME/sloppy_sdss_access`) **grows without bound.**
>
> * Nothing limits size or age.
> * Nothing verifies that an existing file still matches the server.
> * `fetch` treats "the target path exists" as "the cache is valid", which is wrong if
>   a download was interrupted — you get a truncated file back, silently, forever.
>
> **A working session over many products will fill a disk.**
>
> What it needs is a size/age policy plus either checksums (as `pooch` does) or a
> length/ETag check. Neither exists.

## Reproduced upstream bugs

`spcoaddobs` contains a deliberately preserved dead branch, marked `BUG-COMPAT`,
because upstream's operator precedence bug makes an APO-suppression branch
unreachable. Reproducing it is what makes parity hold — but it means **this package
is knowingly wrong in the same way**. It should be fixed in both places together.
See [Migrating]({{< relref "/docs/migrating#2-dead-branch-in-spcoaddobs" >}}).

## Six derivations are not covered by parity

`configgrp`, `configsubmodule`, `platedir`, `definitiondir`, `plategrp` and
`plateid6` are reachable only from `external` products, so the differential check
cannot exercise them. They are unit-tested and **explicitly exempted** from the
coverage gate rather than silently counted — but they have no differential guarantee.

## Not implemented at all

| | issue |
|---|---|
| No CLI | [#94](https://github.com/sdss/sdss_access/issues/94) |
| No progress bars | [#104](https://github.com/sdss/sdss_access/issues/104) |
| No mirror failover | [#102](https://github.com/sdss/sdss_access/issues/102) |
| No rsync or curl transport | — |
| No DR7–DR12 | — |
| No resume on interrupted transfer | — |
| No CI | — |

`SDSS(mirror=True)` selects `https://dev-mirror.sdss.org/sas` statically; nothing
falls back between hosts.

"No rsync or curl transport" means those two *transports* are absent, not that
downloads are. `Access` fetches over HTTPS via `fsspec`, concurrently, and adds
streaming and caching that neither legacy transport had — see
[Remote access]({{< relref "/docs/remote-access" >}}). It matters only if you need a
mirrored `rsync://` tree, or work somewhere HTTPS is blocked.

## Scope, restated

Legacy SDSS-1–3 (DR7–DR12) is deliberately out of scope — that stays with
`sdss-access` + `sdss-tree`, where the SVN/module/plate machinery earns its keep.
SDSS-4 (DR13–DR17) was added as an experiment and drags DR8–DR12 in by inheritance;
it resolves correctly where it resolves, but the `$PRODUCT_ROOT` class of paths
cannot be compiled at all.
