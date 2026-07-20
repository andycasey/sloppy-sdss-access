---
title: Releases
weight: 8
---

# Releases

Thirteen releases are available.

```python
from sloppy_sdss_access import known_releases
known_releases()
```

```
('dr13', 'dr14', 'dr15', 'dr16', 'dr17', 'dr18', 'dr19', 'dr20',
 'ipl1', 'ipl2', 'ipl3', 'ipl4', 'sdsswork')
```

| release | phase | date | current | public | products | `external` | `broken` | inherits |
|---|---|---|---|---|---|---|---|---|
| `dr13` | 4 | 2016-07-31 | | ✓ | 316 | 34 | 0 | dr8→dr12 |
| `dr14` | 4 | 2017-07-31 | | ✓ | 318 | 34 | 0 | dr8→dr13 |
| `dr15` | 4 | 2018-12-10 | | ✓ | 327 | 34 | 0 | dr8→dr14 |
| `dr16` | 4 | 2019-12-09 | | ✓ | 373 | 34 | 2 | dr8→dr15 |
| `dr17` | 4 | 2021-12-06 | | ✓ | 420 | 34 | 2 | dr8→dr16 |
| `dr18` | 5 | 2022-12-05 | ✓ | ✓ | 96 | 9 | 0 | — |
| `dr19` | 5 | 2025-07-10 | ✓ | ✓ | 334 | 14 | 4 | dr18 |
| `dr20` | 5 | 2026-07-30 | ✓ | **not yet** | 412 | 15 | 5 | dr18, dr19 |
| `ipl1` | 5 | 2022-10-25 | | ✗ | 103 | 0 | 0 | — |
| `ipl2` | 5 | 2023-03-01 | | ✗ | 107 | 0 | 0 | ipl1 |
| `ipl3` | 5 | 2023-11-01 | ✓ | ✗ | 215 | 14 | 13 | — |
| `ipl4` | 5 | 2025-07-15 | ✓ | ✗ | 228 | 15 | 12 | ipl3 |
| `sdsswork` | 5 | — | ✓ | ✗ | 463 | 15 | 3 | — |

**3,712 product definitions** in total; **1,958** across the 8 SDSS-5 releases.

* **`external`** — templates rooted at a software-checkout variable, not at SAS data.
  See [below](#the-product_root-problem).
* **`broken`** — templates referencing an env var the release chain never defines.
  See [Migrating]({{< relref "/docs/migrating#bugs-this-surfaced" >}}).
* **public** — computed from the release date, not hardcoded. See
  [Authentication]({{< relref "/docs/authentication#the-dr20-date-nuance" >}}).

```python
from sloppy_sdss_access import SDSS
repr(SDSS("dr19")), repr(SDSS("dr20")), repr(SDSS("sdsswork"))
```

```
"SDSS(release='dr19', products=334, public, date=2025-07-10)"
"SDSS(release='dr20', products=412, collaboration, date=2026-07-30)"
"SDSS(release='sdsswork', products=463, collaboration, date=None)"
```

Release names are normalised for lookup — `SDSS("DR-19")` and `SDSS("dr19")` resolve
to the same release — and `load()` is `lru_cache`d, so repeated construction is free.

## SDSS-5

`sdsswork`, `ipl1`–`ipl4`, `dr18`–`dr20`. This is what the package was built for.
`sdsswork` is the live working release and the largest at 463 products.

Note that `ipl1`/`ipl2` and `ipl3`/`ipl4` are **two separate inheritance chains** —
`ipl3` does not inherit from `ipl2`.

## SDSS-4 (DR13–DR17)

Added as an experiment. Parity against the legacy package is 16,820 comparisons with
zero divergences, so resolution is trustworthy where it resolves at all.

> [!WARNING]
> ### SDSS-4 is not separable from SDSS-III
>
> DR13–DR17 all chain back to **DR8**, and the leaf configs are nearly empty on their
> own — DR14 defines 3 path entries; DR8 defines 164. Ingesting SDSS-4 means ingesting
> DR8–DR12 by inheritance.
>
> DR13–DR17 are therefore exposed as releases; **DR7–DR12 are inherited-from but not
> offered.** `SDSS("dr12")` raises.

## The `$PRODUCT_ROOT` problem

The whole approach rests on one property: **every `$ENVVAR` in a tree template is
defined inside the tree config itself**, rooted at `FILESYSTEM`, so it can be
resolved at build time into a path relative to the SAS root.

A large minority of SDSS-4 templates break that property. They do not point at SAS
data at all — they point at **svn/git software product checkouts on the user's own
machine**:

```ini
mangaslitmap = $PRODUCT_ROOT/repo/manga/mangacore/tags/v1_2_3/slitmaps/@plategrp|/{plate}/slitmap-{plate}-{mjd}-{plugging:0>2d}.par
plateHoles   = $PLATELIST_DIR/plates/@platedir|/plateHoles-@plateid6|.par
```

`$PRODUCT_ROOT` is defined in **no** tree config. `tree.py` synthesises it at runtime
from the first of `$PRODUCT_ROOT`, `$SDSS_GIT_ROOT`, `$SDSS_SVN_ROOT`,
`$SDSS_INSTALL_PRODUCT_ROOT`, `$SDSS_PRODUCT_ROOT`, `$SDSS4_PRODUCT_ROOT`, falling
back to one directory above `$SAS_BASE_DIR`. The products underneath it
(`platelist`, `speclog`, `mangacore`, `mangapreim`, `bosstilelist`) are separately
versioned repositories you check out yourself, pinned to tags like `v1_2_3` written
into the template.

These are **irreducibly environment-dependent**. There is no build-time value to bake
in, because the answer is a property of the machine, not of the archive. **34 paths
per SDSS-4 release** are in this class (and 0–15 per SDSS-5 release — `ipl1` and
`ipl2` have none); they are marked `external` in the registry.

```python
SDSS("dr17").product("plateHoles").external
SDSS("dr17").product("plateHoles").template
```

```
('PRODUCT_ROOT',)
'$PRODUCT_ROOT/data/sdss/platelist/trunk/plates/@platedir|/plateHoles-{plateid:0>6}.par'
```

> [!INFO]
> **`external` products refuse to resolve, by design.**
>
> ```python
> SDSS("dr17").path("plateHoles", plateid=8000)
> ```
>
> ```
> UnresolvableProduct: 'plateHoles' is not archive data: its template is rooted at
> $PRODUCT_ROOT, an svn/git software product checkout whose location is a property of
> your machine, not of the SAS. ...
> ```
>
> `paths.py` checks both `product.broken` and `product.external`, so a software-product
> path never silently comes back with a literal `$VAR` in it. Detect the case ahead of
> time with `SDSS(r).product(sp).external`.

### Why this is the design flaw worth fixing

`sdss_access` treats "a file on the SAS" and "a file in a source checkout" as the
same kind of object, resolved by the same `$ENVVAR` mechanism, differing only in
which variables happen to be set. That is why the package needs `os.environ` at all,
why it carries `check_modules()` and `force_modules`, and why `$SAS_BASE_DIR` feels
mandatory.

Data paths and code paths have genuinely different semantics:

| | data on the SAS | a product checkout |
|---|---|---|
| mutability | immutable, archived | mutable |
| addressability | by URL | local only |
| versioning | by release | by svn/git tag |
| per user | identical for everyone | different on every machine |

Collapsing them forces the *data* case — the overwhelmingly common one — to pay the
environmental cost of the *code* case. Splitting them is what buys the
zero-environment-variable property for everything else.

Doing it properly means an explicit second resolver:

```python
SDSS4(release="dr17", product_root="~/software")   # not implemented
```

so software-product paths are opt-in, obviously environment-dependent at the call
site, and cannot silently contaminate data-path resolution.

## The BOSS/EBOSS section deletion

`tree.py` resolves a variable conflict by deleting an entire config section:

```python
if 'EBOSS' in cfg.sections() and 'BOSS' in cfg.sections():
    cfg.remove_section('BOSS')
```

The intent is right. `[EBOSS]` redefines `BOSS_SPECTRO_REDUX` from `$BOSS_ROOT` to
`$EBOSS_ROOT`, and EBOSS should win for DR13+. Verified against the archive:
`dr17/eboss/spectro/redux/` exists; `dr17/boss/spectro/redux/` does not.

But deleting the whole section also discards **`BOSS_GALAXY_REDUX`**, which only
`[BOSS]` defines. So for DR13–DR17, `sdss_access` cannot resolve it and returns a
path with the variable still in it:

```bash
$ python -c "                              # the real sdss-access, in its own venv
from sdss_access import Path
print(Path(release='dr17').full('portsmouth_emlinekin', galaxy_vers='v1', run2d='v5_13_2'))"
```

```
$BOSS_GALAXY_REDUX/v1/portsmouth_emlinekin-v5_13_2.fits
```

This build overrides per **variable** rather than per section, so the definition
survives and points at the EBOSS root:

```python
SDSS("dr17").path("portsmouth_emlinekin", galaxy_vers="v1", run2d="v5_13_2")
```

```
'dr17/eboss/spectro/redux/galaxy/v1/portsmouth_emlinekin-v5_13_2.fits'
```

**11 products are affected in each of DR13–DR17**: the `portsmouth_*`,
`granada_fsps*` and `wisconsin_pca*` VACs. These account for the 275
`legacy unresolved` results in the parity run (55 products × 5 scenarios).

> [!WARNING]
> **Practical impact is low, and this build is not "correct" either.**
>
> Those VACs exist only in DR12 — `dr12/boss/spectro/redux/galaxy/` is real, and no
> DR13+ equivalent exists under either root. DR13–DR17 are carrying stale templates
> forward.
>
> This build's answer is **well-formed but points at nothing real**. It is *better*
> than a literal `$VAR`, not *correct*.

## Release defaults

Only DR19 carries release-implied pipeline versions:

```python
SDSS("dr19").defaults
SDSS("dr20").defaults
SDSS("sdsswork").defaults
```

```
{'run2d': 'v6_1_3', 'apred': '1.4', 'v_astra': '0.6.0'}
{}
{}
```

See [Path resolution]({{< relref "/docs/path-resolution#release-defaults" >}}) and
[Limitations]({{< relref "/docs/limitations" >}}).
