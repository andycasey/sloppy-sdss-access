---
title: Path resolution
weight: 5
---

# Path resolution

Resolution is three steps, in this order:

1. **Merge** release defaults under your supplied keys.
2. **Substitute** `{brace}` placeholders with `str.format()`.
3. **Apply derivations** — the `@name|` markers — as pure functions of the keys.

Then empty path segments are collapsed and the result is stripped of leading and
trailing slashes. That is the whole algorithm; there is no filesystem access and no
environment lookup.

## Templates

A compiled template looks like this:

```python
from sloppy_sdss_access import SDSS
print(SDSS("dr19").describe("specFull"))
```

```
specFull (dr19)
  template : dr19/spectro/boss/redux/{run2d}/spectra/full/@pad_fieldid|@isplate|/{mjd}/spec-@pad_fieldid|-{mjd}-{catalogid}.fits
  required : catalogid, fieldid, mjd, run2d
  optional : -
  derived  : isplate, pad_fieldid
  compress : maybe
```

Two kinds of placeholder:

| syntax | meaning |
|---|---|
| `{run2d}`, `{mjd}` | a key you supply, substituted literally |
| `@pad_fieldid\|`, `@isplate\|` | a **derivation** — a function of the keys |

Format specs work as in any Python format string — `{num:0>8}` zero-pads to 8, and
`{plateid:0>6}` to 6.

> [!INFO]
> Note that the template begins with `dr19/`, not `$BOSS_SPECTRO_REDUX/`. The
> environment variable was resolved when the registry was compiled. See
> [Regenerating the registry]({{< relref "/docs/registry" >}}).

Get every template at once through the compat shim:

```python
from sloppy_sdss_access import Path
len(Path(release="dr19").templates)
```

```
334
```

## Required vs optional keys

Required-ness is **declared per product** at build time, not guessed at runtime.

```python
dr19 = SDSS("dr19")
dr19.keys("apStar")
```

```
('apred', 'healpix', 'obj', 'telescope')
```

Omit one and you get an error naming it:

```python
dr19.path("apStar", healpix=12345, obj="2M00000032+5737103")
```

```
MissingKeys: "'apStar' requires telescope. Full key set: apred, healpix, obj, telescope."
```

Supply them and it resolves:

```python
dr19.path("apStar", healpix=12345, obj="2M00000032+5737103", telescope="apo25m")
```

```
'dr19/spectro/apogee/redux/1.4/stars/apo25m/12/12345/apStar-1.4-apo25m-2M00000032+5737103.fits'
```

(`apred` came from the DR19 defaults, and `12` from the `healpixgrp` derivation.)

### The rule for optional

> [!INFO]
> **A key is optional only where its absence has a defined, meaningful result** — not
> merely where the Python function happens to tolerate `None`.
>
> Anything whose output lands in a path *segment* is required. Only genuine flags are
> optional: a blank `component` (no discernible companion), a merged-observatory
> `obs`, an `ftype` that defaults to FITS, a `telescope` that only refines a prefix.

This distinction matters. `pad_fieldid` returns `""` when `fieldid` is missing, but
its output is interpolated into the *filename* — so treating `fieldid` as optional
yields a silently malformed `spec--59797-….fits`, which is exactly the legacy bug.

A real optional key:

```python
work = SDSS("sdsswork")
print(work.describe("ap1D"))
```

```
ap1D (sdsswork)
  template : sdsswork/mwm/apogee/spectro/redux/{apred}/exposures/{instrument}/{mjd}/@apgprefix|1D-{chip}-{num:0>8}.fits
  required : apred, chip, instrument, mjd, num
  optional : telescope
  derived  : apgprefix
  compress : maybe
```

```python
work.path("ap1D", apred="1.4", chip="a", instrument="apogee-n", mjd=59797, num=1)
work.path("ap1D", apred="1.4", chip="a", instrument="apogee-n", mjd=59797, num=1, telescope="lco25m")
```

```
'sdsswork/mwm/apogee/spectro/redux/1.4/exposures/apogee-n/59797/ap1D-a-00000001.fits'
'sdsswork/mwm/apogee/spectro/redux/1.4/exposures/apogee-n/59797/as1D-a-00000001.fits'
```

Absent `telescope`, `apgprefix` falls back to `instrument` and yields `ap`. Supplied,
it takes precedence and yields `as`.

> [!WARNING]
> **Optional keys are not filled with a blank.** Every key appearing literally in a
> template is required, so `.format()` never needs them, and the derivations already
> treat absence as their default. An injected `""` would be worse than nothing —
> `apgprefix` would read it as a supplied-but-invalid telescope and raise.

## `any_of`

Some derivations are satisfied by any **one** of a set of keys. `apgprefix` accepts
either `telescope` or `instrument`. The registry can record this as an `any_of`
group, and `path()` enforces it:

```python
for group in product.any_of:
    if not any(merged.get(k) for k in group):
        raise MissingKeys(f"{species!r} requires one of: {', '.join(group)}.")
```

> [!WARNING]
> **No product currently uses it.** Measured across all 13 releases:
>
> ```python
> from sloppy_sdss_access import known_releases, load
> sum(1 for r in known_releases() for p in load(r).products.values() if p.any_of)
> ```
>
> ```
> 0
> ```
>
> In every template that calls `apgprefix`, `instrument` also appears literally as a
> `{instrument}` placeholder, which already makes it required — so the `any_of` group
> collapses to "required `instrument`, optional `telescope`", as seen in `ap1D` above.
> The mechanism is live code and is exercised by unit tests, but it is currently
> dormant in the shipped registry.

## Release defaults

Some keys are implied by the release itself. DR19 knows its own pipeline versions:

```python
SDSS("dr19").defaults
```

```
{'run2d': 'v6_1_3', 'apred': '1.4', 'v_astra': '0.6.0'}
```

They are merged **under** your keys — `{**defaults, **keys}` — so anything you pass
wins:

```python
dr19.path("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
dr19.path("specLite", fieldid=15000, mjd=59146, catalogid=4375924756, run2d="v6_0_4")
```

```
'dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'dr19/spectro/boss/redux/v6_0_4/spectra/lite/15000p/59146/spec-15000-59146-4375924756.fits'
```

Note how overriding `run2d` changes more than one segment: `pad_fieldid` stops
zero-padding and `isplate` adds the `p` flag, because `v6_0_4` predates the
reorganised BOSS layout.

This is [#73](https://github.com/sdss/sdss_access/issues/73) and
[#98](https://github.com/sdss/sdss_access/issues/98).

> [!DANGER]
> **`RELEASE_DEFAULTS` is seeded for DR19 only.** The other twelve releases return
> `{}`, and you must pass every pipeline version yourself. Their versions need to come
> from the release coordinators; they are not in `tree`.
>
> ```python
> SDSS("dr20").defaults    # {}
> SDSS("sdsswork").defaults # {}
> ```

## Derivations

Derivations are `sdss_access`'s "special functions", ported to plain module-level
functions in `sloppy_sdss_access/derive.py`. They compute a path *segment* from one or more
keys — typically grouping directories that keep any one folder from holding a
million files.

Three differences from upstream:

* They are **plain functions**, not methods on a 1,900-line class, so they are
  individually testable and importable.
* The keys each one consumes are **declared** (in `DERIVATION_KEYS`, in the builder)
  rather than recovered by AST-parsing the function's own source at runtime. This is
  both the speed win and what makes optional keys tractable.
* They **never read `os.environ`**.

Behaviour is otherwise intentionally identical, bug-for-bug, so resolved paths can
be diffed against the legacy implementation. Known upstream quirks are marked
`BUG-COMPAT` in the source.

### All 24 derivations

```python
from sloppy_sdss_access.derive import DERIVATIONS
len(DERIVATIONS)
```

```
24
```

| derivation | keys | purpose |
|---|---|---|
| `healpixgrp` | `healpix` | HEALPix group directory: `healpix // 1000` |
| `cat_id_groups` | `cat_id` | Two-level grouping on catalogue id, ~1,000 files per folder at 10M sources |
| `sdss_id_groups` | `sdss_id` | Two-level grouping on SDSS id |
| `configgrp` | `configid` | Configuration group directory, `NNNNXX` |
| `configsubmodule` | `configid` | Configuration submodule directory, `NNNXXX` |
| `tilegrp` | `tileid` | LVM tile group directory, `NNNNXX` |
| `platedir` | `plateid` | Plate directory, `NNNNXX/NNNNNN` |
| `apgprefix` | *either* `telescope` / `instrument` | APOGEE file prefix (`ap`/`as`) |
| `component_default` | `component` *(opt)* | Washington Multiplicity Catalog component, blank when absent |
| `isplate` | `run2d` | `p` flag for the run2d versions that still used plates |
| `pad_fieldid` | `fieldid`, `run2d` | Zero-pad fieldid to 6 digits, except on the run2d versions that did not |
| `fieldgrp` | `fieldid`, `run2d` | Field group directory, `NNNXXX`, on the reorganised layout only |
| `sptypefolder` | `run2d` | Subfolder for the reorganised BOSS layout, by product species |
| `spcoaddfolder` | `run2d`, `coadd` | Subfolder for custom BOSS coadds |
| `spcoaddgrp` | `run2d`, `coadd` | Field-group analog for custom BOSS coadds |
| `epochflag` | `run2d` | `-epoch` suffix on the reorganised layout |
| `spcoaddobs` | `obs` *(opt)*, `run2d` | Observatory suffix for custom coadds — contains a `BUG-COMPAT` dead branch |
| `mos_target_num` | `num`, `ftype` *(opt)* | MOS target file number; blank for Parquet |
| `mos_target_num2` | `num`, `ftype` *(opt)* | …zero-padded to 2 |
| `mos_target_num3` | `num`, `ftype` *(opt)* | …zero-padded to 3 |
| `plateid6` | `plateid` | Plate ID padded to 6 characters, except for 5-digit-plus plates |
| `plategrp` | `plate` | Plate group directory, `NNNNXX` |
| `definitiondir` | `designid` | Design definition group directory, `NNNNXX` |
| `spectrodir` | `run2d` | `SPECTRO_REDUX` or `BOSS_SPECTRO_REDUX`, depending on `run2d` |

> [!INFO]
> **`spectrodir` is the one exception to the zero-environment rule** — it returns a
> *root directory* rather than a path fragment. Upstream it reads `os.environ`
> directly. Here the two candidate roots are resolved at build time and handed in via
> a reserved `_env` key on the `Release`, so the property survives.

Two upstream special functions (`apginst`, `mos_target_num_underscore`) are used by
no SDSS-5 template and were dropped. A test asserts that none of the remaining 24
become dead again.

**Coverage:** the parity harness exercises **18 of 24** with ≥2 distinct outputs
each. `configgrp`, `configsubmodule` and `platedir` are reachable only from
`external` products, so parity cannot cover them; they are unit-tested and
explicitly exempted from the gate.

## Errors

| exception | base | raised when |
|---|---|---|
| `UnknownProduct` | `KeyError` | no such product species in this release |
| `MissingKeys` | `KeyError` | a required key (or `any_of` group) was not supplied |
| `UnresolvableProduct` | `ValueError` | the template references an env var this release never defines, or an unknown `@derivation\|` |

```python
dr19.path("nosuchthing")
```

```
UnknownProduct: "'nosuchthing' is not in release 'dr19'."
```

Near-misses get a suggestion where one exists — `product()` globs `*{species}*` and
appends up to five candidates.

```python
dr19.path("asR", mjd=59797, chip="a", num=1)
```

```
UnresolvableProduct: 'asR' in 'dr19' references $APOGEE_DATA_S, which this release
never defines. This is a defect in the upstream tree config; sdss_access silently
returns a path with the literal variable in it.
```

> [!DANGER]
> **`external` products do not raise — they emit a literal `$VAR`.**
>
> Products rooted at software-checkout variables (`$PRODUCT_ROOT`, `$PLATELIST_DIR`, …)
> are marked `external` in the registry, but `paths.py` checks only `broken`, not
> `external`. Verified:
>
> ```python
> SDSS("dr17").path("plateHoles", plateid=8000)
> ```
>
> ```
> UnresolvableProduct: 'plateHoles' is not archive data: its template is rooted at $PRODUCT_ROOT, an svn/git software product checkout whose location is a property of your machine, not of the SAS. There is no build-time value to substitute, so this cannot be resolved here. See the $PRODUCT_ROOT notes in the README; a separate opt-in resolver taking an explicit product_root is the intended fix.
> ```
>
> These refuse to resolve, raising `UnresolvableProduct`, because there is no
> build-time value to substitute — the location is a property of your machine,
> not of the archive. Check `SDSS(r).product(sp).external` to detect them up front.
> See [Limitations]({{< relref "/docs/limitations" >}}).

## Introspection

```python
dr19.search("astraAllStar*")
```

```
['astraAllStarASPCAP', 'astraAllStarApogeeNet', 'astraAllStarAstroNN',
 'astraAllStarAstroNNdist', 'astraAllStarBossNet', 'astraAllStarCorv',
 'astraAllStarLineForest', 'astraAllStarMDwarfType', 'astraAllStarSlam',
 'astraAllStarSnowWhite', 'astraAllStarThePayne']
```

| call | returns |
|---|---|
| `search(pattern)` | sorted list of matching species, case-insensitive glob |
| `keys(species)` | every key the product accepts, required and optional |
| `describe(species)` | the multi-line summary shown above |
| `product(species)` | the `Product` dataclass — `.template`, `.required`, `.optional`, `.derivations`, `.any_of`, `.external`, `.broken`, `.compression`, `.may_be_compressed` |
| `defaults` | release-implied keys |
| `len(release)`, `in`, `iter` | product count, membership, iteration |
