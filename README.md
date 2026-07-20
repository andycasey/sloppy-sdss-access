# sloppy-sdss-access

A prototype replacement for `sdss_access`, built on modern tooling.

```python
from sloppy_sdss_access import SDSS

dr19 = SDSS("dr19")

dr19.path("astraAllStarASPCAP")
# 'dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'

dr19.url("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
# 'https://data.sdss5.org/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
```

## The core idea

Every `$ENVVAR` in a tree path template is itself defined *inside the same tree
config file*, as `%(...)s` interpolations rooted at `FILESYSTEM`. So they can all
be resolved **once, at build time**, and each template stored as a plain path
relative to the SAS root.

That single change removes the need for environment variables entirely:

| | `sdss_access` | `sloppy-sdss-access` |
|---|---|---|
| env vars injected into `os.environ` | **+97** | **+0** |
| two releases in one session | mutate shared global state | independent frozen objects |
| dependencies for path resolution | `sdss-tree`, `requests`, `six`, … | **none** |
| transports | rsync, curl, http | anything `fsspec` speaks (https, s3, file, …) |

**Resolution speed** (5,000 iterations each, same machine, DR19):

| product | `sdss5` | `sdss_access` | speedup |
|---|---|---|---|
| `astraAllStarASPCAP` (0 derivations) | 0.66 µs | 10.8 µs | 16× |
| `apStar` (1 derivation) | 1.56 µs | 55.1 µs | 35× |
| `specLite` (2 derivations) | 2.41 µs | 149.5 µs | 62× |

The gap widens with the number of derivations, because `sdss_access` AST-parses
its own special-function source code and stats the filesystem on *every* call.

## No environment variables required

Path resolution consults the environment **not at all**. With no `SAS_BASE_DIR`
and no `~/.netrc`, `path()` and `url()` work unchanged, and public DR data needs
no credentials whatsoever.

`local()` is the one method that needs a local root, and it takes the first of:
explicit `SDSS(root=...)`, then `$SAS_BASE_DIR` if set (read-only, purely so an
existing `sdss_access` machine works out of the box), then `~/sas`.

For collaboration data without a netrc, credentials come from `$SDSS_USER` /
`$SDSS_PASSWORD`, from explicit arguments, or from an opt-in prompt:

```python
Access(SDSS("sdsswork"), username="...", password="...")   # explicit
Access(SDSS("sdsswork"))                                   # $SDSS_USER/$SDSS_PASSWORD
Access(SDSS("sdsswork"), allow_prompt=True)                # ask on a terminal
```

If none are available the `AuthError` spells out all four options.

## Install

```bash
uv add sloppy-sdss-access          # or: pip install sloppy-sdss-access
uv add "sloppy-sdss-access[s3]"    # + s3fs for cloud buckets
```

Installs as `sloppy_sdss_access`:

```python
from sloppy_sdss_access import SDSS, Access
```

`fsspec` and `aiohttp` are required rather than optional: a package whose point is
fetching data should be able to fetch data straight after install. Resolving a path
still imports nothing beyond the standard library.

## What it does

**Paths.** 1,958 product definitions across all 8 SDSS-5 releases
(`sdsswork`, `ipl1`–`ipl4`, `dr18`–`dr20`), compiled to a static registry.

```python
dr19.search("astraAllStar*")     # glob the product list
dr19.keys("apStar")              # ('apred', 'healpix', 'obj', 'telescope')
print(dr19.describe("specFull")) # template, required/optional keys, derivations
```

**Release-implied versions** — [#73](https://github.com/sdss/sdss_access/issues/73),
[#98](https://github.com/sdss/sdss_access/issues/98).
DR19 knows its own pipeline versions, so you don't restate them:

```python
dr19.defaults   # {'run2d': 'v6_1_3', 'apred': '1.4', 'v_astra': '0.6.0'}
```

Only DR19 is seeded — see *Not done*.

**Required vs optional keys** — [#100](https://github.com/sdss/sdss_access/issues/100),
partly. Required-ness is declared per product; omitting a required key raises an
error naming it. A key is optional only where absence has a defined meaning (a
blank `component`, a merged-observatory `obs`, `ftype` defaulting to FITS).
Per-key *default values* are not implemented — only release-wide defaults.

**Multiple releases at once** — [#34](https://github.com/sdss/sdss_access/issues/34),
[#97](https://github.com/sdss/sdss_access/issues/97). `SDSS` is a frozen
dataclass holding its own registry. Nothing is global, so the interference bug
in #34 cannot occur *within SDSS-5*. Mixing DR17 and DR19 still means running
legacy `sdss_access` alongside, which does replant the tree.

**Authentication** — [#95](https://github.com/sdss/sdss_access/issues/95).
Public DRs need no credentials. `sdsswork`, the IPLs, and any DR whose release
date has not yet passed (DR20 is dated 2026-07-30) sit behind HTTP Basic auth.
Credentials resolve from the first source that supplies them:

1. passed explicitly — `Access(..., username=..., password=...)`
2. `$SDSS_USER` / `$SDSS_PASSWORD` — CI, containers
3. `~/.netrc` keyed by host — the existing `sdss_access` setup
4. an interactive prompt — **opt-in** via `allow_prompt=True`, skipped without a TTY

Passwords are kept out of `repr`/`str`, and a world-readable netrc warns. Unlike
`sdss_access.sync.auth`, nothing prompts implicitly — a library that blocks on
`input()` inside a batch job is a bug.

**Streaming** — [#96](https://github.com/sdss/sdss_access/issues/96).
Read a header without transferring the file:

```python
from sloppy_sdss_access import Access
a = Access(dr19)

with a.open("astraAllStarASPCAP") as fp:
    header = fp.read(1024)
```

fsspec fetches one 5 MiB block to serve that read, not the full 1.17 GB file.

**Compression probing** — [#66](https://github.com/sdss/sdss_access/issues/66).
Tree templates and the SAS disagree about compression more often than you would
hope: `sdsswork`'s `astraAllStarASPCAP` is templated `.fits` but stored
`.fits.gz` (DR19's template has it right). `Access` returns the real variant:

```python
a.uri("astraAllStarASPCAP", v_astra="0.6.0")          # ...-0.6.0.fits      (as templated)
a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0")  # ...-0.6.0.fits.gz   (as stored)
```

Probing is *declared in the registry*, not attempted blindly. Each product
carries `compression` (the suffix its template already names) and
`may_be_compressed`:

| | products | probes |
|---|---|---|
| template already names `.gz`/`.bz2`/`.fz` | 142 | none |
| extension never compressed (`.png`, `.parquet`, `.h5`, `.apz`) | 452 | none |
| `may_be_compressed` | 1,364 | one, then cached |

and the correction is learned **once per species**, not per file — the SAS does
not compress one `mwmStar` and not the next. Measured against the live SAS:

```
mwmStar, 5 files        -> 1 exists() call   (learned {'mwmStar': ''})
sdsswork astraAllStar…  -> 2 calls, then 0   (learned '.gz')
dr19 astraAllStar…      -> 0 calls           (.gz already in template)
probe_compression=False -> 0 calls
```

So a loop over 10,000 stars costs one extra request, not 10,000.

`sdss_access` does this by `stat`-ing the *local* filesystem, so it only
self-corrects on a machine with a SAS mount — remotely it returns the broken
`.fits` URL just as this did before.

**Async downloads** — [#99](https://github.com/sdss/sdss_access/issues/99).

```python
a.fetch_many(items, concurrency=8)              # blocking
await a.afetch_many(items)                      # inside an event loop
a.fetch_many(items, skip_missing=True)          # missing files -> None, #89
```

Genuinely async (`fsspec` `asynchronous=True` + `asyncio.gather` under a
semaphore), not merely named so. Downloads are content-cached, so a repeat call
is ~1 ms rather than a re-transfer.

**Cloud** — [#101](https://github.com/sdss/sdss_access/issues/101).
`Access(dr19, protocol="s3", bucket=...)` constructs `s3://` URIs. **Untested** —
SDSS data is not on MAST yet, no bucket exists to check against, and S3
credentials are not wired.

## SDSS-4 (DR13–DR17)

Added as an experiment. 3,712 products across 13 releases; parity is 16,820
comparisons with zero divergences.

**SDSS-4 is not separable from SDSS-III.** DR13–DR17 all chain back to DR8, and
the leaf configs are nearly empty on their own (DR14 defines 3 path entries;
DR8 defines 164). Ingesting SDSS-4 means ingesting DR8–DR12 by inheritance.
DR13–DR17 are exposed as releases; DR7–DR12 are inherited-from but not offered.

### The `$PRODUCT_ROOT` problem — why some SDSS-4 paths cannot be compiled

The whole approach here rests on one property: **every `$ENVVAR` in a tree
template is defined inside the tree config itself**, rooted at `FILESYSTEM`, so
it can be resolved at build time into a path relative to the SAS root.

A large minority of SDSS-4 templates break that property. They do not point at
SAS data at all — they point at **svn/git software product checkouts on the
user's own machine**:

```
mangaslitmap = $PRODUCT_ROOT/repo/manga/mangacore/tags/v1_2_3/slitmaps/@plategrp|/{plate}/slitmap-{plate}-{mjd}-{plugging:0>2d}.par
plateHoles   = $PLATELIST_DIR/plates/@platedir|/plateHoles-@plateid6|.par
```

`$PRODUCT_ROOT` is defined in **no** tree config. `tree.py` synthesises it at
runtime from the first of `$PRODUCT_ROOT`, `$SDSS_GIT_ROOT`, `$SDSS_SVN_ROOT`,
`$SDSS_INSTALL_PRODUCT_ROOT`, `$SDSS_PRODUCT_ROOT`, `$SDSS4_PRODUCT_ROOT`,
falling back to one directory above `$SAS_BASE_DIR`. The products underneath it
(`platelist`, `speclog`, `mangacore`, `mangapreim`, `bosstilelist`) are
separately versioned repositories you check out yourself, pinned to tags like
`v1_2_3` written into the template.

These are therefore **irreducibly environment-dependent**. There is no
build-time value to bake in, because the answer is a property of the machine,
not of the archive. Roughly 150 SDSS-4 paths are in this class; they are marked
`external` in the registry and refuse to resolve rather than emitting a path
with a literal `$PRODUCT_ROOT` in it.

**This is the design flaw the split is meant to address.** `sdss_access` treats
"a file on the SAS" and "a file in a source checkout" as the same kind of
object, resolved by the same `$ENVVAR` mechanism, differing only in which
variables happen to be set. That is why the package needs `os.environ` at all,
why it carries `check_modules()` and `force_modules`, and why `$SAS_BASE_DIR`
feels mandatory. Data paths and code paths have genuinely different semantics:
data is immutable, archived, addressable by URL, and identical for every user;
a product checkout is mutable, local, version-pinned, and different per machine.
Collapsing them forces the *data* case — the overwhelmingly common one — to pay
the environmental cost of the *code* case.

Splitting them is what buys the zero-env-var property for everything else. Doing
it properly means an explicit second resolver, e.g.

```python
SDSS4(release="dr17", product_root="~/software")   # not implemented
```

so software-product paths are opt-in, obviously environment-dependent at the
call site, and cannot silently contaminate data-path resolution. Until that
exists, `external` products raise.

### The BOSS/EBOSS section deletion

`tree.py` resolves a variable conflict by deleting an entire config section:

```python
if 'EBOSS' in cfg.sections() and 'BOSS' in cfg.sections():
    cfg.remove_section('BOSS')
```

The intent is right — `[EBOSS]` redefines `BOSS_SPECTRO_REDUX` from
`$BOSS_ROOT` to `$EBOSS_ROOT`, and EBOSS should win for DR13+. Verified against
the archive: `dr17/eboss/spectro/redux/` exists, `dr17/boss/spectro/redux/` does
not.

But deleting the whole section also discards `BOSS_GALAXY_REDUX`, which only
`[BOSS]` defines. So for DR13–DR17, `sdss_access` cannot resolve it and returns
a path with the variable still in it:

```python
Path(release="dr17").full("portsmouth_emlinekin", galaxy_vers="v1", run2d="v5_13_2")
# '$BOSS_GALAXY_REDUX/v1/portsmouth_emlinekin-v5_13_2.fits'
```

11 products are affected in each of DR13–DR17: the `portsmouth_*`,
`granada_fsps*`, and `wisconsin_pca*` VACs. This build overrides per *variable*
rather than per section, so the definition survives and points at the EBOSS root.

**Practical impact is low.** Those VACs exist only in DR12
(`dr12/boss/spectro/redux/galaxy/` is real; no DR13+ equivalent exists under
either root), so DR13–DR17 are carrying stale templates forward. This build's
answer is well-formed but points at nothing real either — it is *better* than a
literal `$VAR`, not *correct*.

## Migrating from `sdss_access`

`from sloppy_sdss_access import Path` keeps working. `full()`, `location()` and `url()`
were verified byte-identical against the real package (`tests/test_compat.py`
pins the reference values).

| legacy | here |
|---|---|
| `Path(release="dr19")` | same, or `SDSS("dr19")` for the native API |
| `.full(sp, **k)` | same — absolute, under `root=`/`$SAS_BASE_DIR`/`~/sas` |
| `.location(sp, **k)` | same — or native `SDSS.path()` |
| `.url(sp, **k)` | same, including the `data.sdss.org` vs `data.sdss5.org` split |
| `RsyncAccess().add(); .set_stream(); .commit()` | `Access(SDSS(r)).fetch_many([(sp, keys), ...])` |
| `HttpAccess().get(sp, **k)` | `Access(SDSS(r)).fetch(sp, **k)` |
| `Auth`/`set_auth(inquire=True)` | `sdss_access.auth` — never prompts unless asked |

> **`SDSS` vs `Path`.** `SDSS` is the native API (`.path()`, `.local()`,
> `.url()`); `Path` is the legacy-shaped shim (`.location()`, `.full()`,
> `.url()`). They resolve identically — `Path` just delegates. New code should
> use `SDSS`.

Things that **deliberately** behave differently:

* **Missing keys raise.** Legacy could emit a malformed path with an empty
  segment (`spec--59797-….fits`); here it is a `MissingKeys` error naming the key.
* **Undefined variables raise.** Legacy returned paths containing a literal
  `$APOGEE_DATA_S`; here it is `UnresolvableProduct`.
* **Release defaults.** `Path("dr19").location("specLite", …)` no longer needs
  `run2d` — DR19 implies `v6_1_3`. Legacy raised `KeyError`.
* **No `os.environ` writes.** Constructing a legacy `Path` replanted the tree and
  overwrote ~97 variables (and `makedirs`-ed your `SAS_BASE_DIR`). Nothing here
  writes to the environment.
* **No rsync or curl.** `RsyncAccess`/`CurlAccess` raise with a pointer to
  `fetch_many()`.
* **DR7–DR12 unavailable.** `Path(release="dr12")` raises at construction.

## Verification

**Parity with `sdss_access`.** `tools/parity_check.py` resolves every product in
every SDSS-5 release with both implementations, under **five key scenarios** each:

```
  dr18       match=435   skipped=9
  dr19       match=1580  skipped=18
  dr20       match=1960  skipped=20
  ipl1       match=515
  ipl2       match=535
  ipl3       match=940   skipped=27
  ipl4       match=1005  skipped=27
  sdsswork   match=2225  skipped=18

  TOTAL: match=9195  skipped=119

  Derivation coverage: 17/20 exercised
    every derivation ran and produced >=2 distinct outputs

  RESULT: PASS
```

9,195 comparisons, zero divergences, zero errors. The 119 skipped are `external`
products (under `$PLATELIST_DIR` etc., outside the SAS) and the 37 `broken` ones
below; neither implementation can resolve them, so they are excluded rather than
counted as passes.

**Why five scenarios, and a coverage gate.** An earlier version of this harness
pinned `run2d="v6_1_3"`, which makes every reorganised-BOSS-layout branch dead.
Ten of the derivations then returned a single constant all run and five were never
called — half of `derive.py` could have been replaced with hardcoded strings and
the check would still have passed. The scenarios now vary `run2d`, `telescope`,
`obs`, `ftype` and numeric magnitude, and the run **fails** unless every
derivation is exercised with ≥2 distinct outputs. Mutation-tested: replacing
`pad_fieldid`, `spcoaddobs`, `sptypefolder` or `healpixgrp` with a constant is
now caught (all four `FAIL`).

Three derivations (`configgrp`, `configsubmodule`, `platedir`) are reachable only
from `external` products, so parity cannot cover them; they are unit-tested and
explicitly exempted from the gate rather than silently counted.

**Known blind spot.** The comparison normalises away `.gz`/`.bz2`/`.zip`/`.fz`
suffixes, because legacy probes the filesystem and nothing exists locally. So
parity says nothing about [#66](https://github.com/sdss/sdss_access/issues/66)
(compressed-file resolution), which is not implemented here at all.

**Against the live SAS** (2026-07-20), public DR19: resolved paths for
`astraAllStarASPCAP` and `specLite` confirmed to exist; 4 real spectra downloaded
concurrently in 3.2 s; a range read from a 1.17 GB file returned valid gzip magic.

**Against collaboration-only `sdsswork`**, with real `~/.netrc` credentials:

- anonymous `HEAD` -> `401 WWW-Authenticate: Basic realm="SDSS-V Science Archive Server (SAS)"`;
  same request with netrc credentials -> `200`
- credential resolution picked up `~/.netrc` and listed collaboration-only
  directories through fsspec
- compression probing corrected `astraAllStarASPCAP-0.6.0.fits` ->
  `.fits.gz` and streamed 64 bytes from the 1.17 GB file
- `fetch_many` downloaded 5 real `mwmStar` spectra concurrently in 6.7 s;
  re-fetch from cache took 1 ms
- a downloaded file opens as valid FITS (5 HDUs) whose `SDSS_ID` header equals
  the `sdss_id` key it was resolved from -- a full key -> path -> auth ->
  download -> correct-file round trip

```bash
pytest                                    # 96 tests
python tools/parity_check.py              # needs sdss-access installed too
```

`sdss-access` must be installed alongside for the differential check; the two have
distinct module names and coexist without interference.

```bash
pip install sdss-access
python tools/parity_check.py
```

## Two bugs this surfaced in the current stack

**1. 37 product definitions reference environment variables their own release
never defines.** `sdss_access` uses `os.path.expandvars`, which leaves unknown
variables untouched, so these silently return a path with a literal `$VAR` in it:

```python
Path(release="dr19").full("asR", mjd=59797, chip="a", num=1)
# '$APOGEE_DATA_S/59797/asR-a-00000001.apz'
```

Affected: `asR`, `cannonStar`, `cannonStar-1m`, `apogee-rc` (dr19/dr20/sdsswork),
`gcam_lco` (dr20), and the `aspcap*`/`apogee*` family in ipl3/ipl4 — full list
printed by `tools/build_registry.py`. Here they raise `UnresolvableProduct`.

**2. Dead branch in `spcoaddobs`.** Upstream reads:

```python
if (('v5' in run2d) or ... or (...) and obs.lower()) == 'apo':
```

`== 'apo'` binds to the whole parenthesised expression, so this compares a
`bool` to a string and is always `False`. The APO-suppression it intends never
happens. Reproduced bug-for-bug in `derive.py` (marked `BUG-COMPAT`) so parity
holds; it should be fixed in both places together.

Both are worth filing against `tree`/`sdss_access` regardless of this prototype's fate.

## Regenerating the registry

The registry is a compiled artifact of `sdss/tree`. Rebuild it with:

```bash
sloppy-sdss-access-build-registry                      # rebuild from the vendored tools/*.cfg
sloppy-sdss-access-build-registry --fetch              # pull latest cfgs from sdss/tree first
sloppy-sdss-access-build-registry --fetch --ref 6.1.0  # ...pinned to a tag, branch, or SHA
sloppy-sdss-access-build-registry --check              # exit 1 if the registry is stale (CI)
```

Without `--fetch`, the command refuses to run when the source configs are absent
(exit 1), and `--check` reports that it cannot compare (exit 2), rather than
rebuilding an empty registry over the shipped one.

`--fetch` downloads `data/*.cfg` over the raw GitHub endpoint (no auth, no `gh`
required) and **follows `base =` chains**, so asking for DR17 also pulls
DR16…DR8 — 18 configs in total for the current release list. The ref and each
file's SHA256 are recorded under `"source"` in the registry, so any given
`registry.json` says which tree revision produced it.

`.github/workflows/update-registry.yml` automates this: it rebuilds weekly (and
on demand, with a `ref` input), runs the tests and the differential check
against `sdss_access`, and opens a **pull request** only if the compiled output
changed. A PR rather than a push is deliberate — one tree edit can move
thousands of paths, which deserves a human diff. A second job fails CI on any PR
whose committed registry does not match its vendored cfgs, so an edited `.cfg`
cannot be merged without a rebuild.

## Layout

```
tools/build_registry.py   offline: tree .cfg -> registry.json (resolves all $ENVVARs)
tools/parity_check.py     differential test vs legacy, with a derivation coverage gate
src/sloppy_sdss_access/registry.py     Product/Release models, release defaults
src/sloppy_sdss_access/paths.py        SDSS: path(), url(), local(), search(), describe()
src/sloppy_sdss_access/derive.py       the 20 "special functions", as pure declared functions
src/sloppy_sdss_access/auth.py         credential resolution: explicit / env / netrc / prompt
src/sloppy_sdss_access/access.py       fsspec: streaming, async fetch, caching, s3
src/sloppy_sdss_access/compat.py       legacy Path/SDSSPath/AccessError shims
src/sloppy_sdss_access/_build.py       the builder (also the console-script entry point)
.github/workflows/        weekly registry rebuild -> PR; staleness check on PRs
```

`derive.py` differs from upstream in that each function *declares* the keys it
consumes (in `DERIVATION_KEYS`) instead of the runtime AST-parsing its own source
to find out — which is both the speed win and what makes optional keys tractable.
Two upstream special functions (`apginst`, `mos_target_num_underscore`) are used
by no SDSS-5 template and were dropped; a test asserts none become dead again.

## Not done

This is a prototype, not a package.

- **`RELEASE_DEFAULTS` is seeded for DR19 only.** The other seven releases return
  `{}`. Their pipeline versions need to come from the release coordinators; they
  are not in `tree`.
- **S3 is untested** and has no credential path.
- **No per-key default values** — only release-wide ones (half of #100).
- **The registry is a build artifact of `tree`.** Long term the templates should
  live somewhere versioned in their own right rather than being scraped.
- **The `DERIVATION_KEYS` table lives in the builder, not next to the functions**,
  so the two can drift. A test catches unused derivations but not wrong key sets.
- Compression probing (#66) covers only the suffixes in `COMPRESSION_SUFFIXES`,
  and `NEVER_COMPRESSED` is a hand-maintained extension list. The underlying
  wrong templates should still be fixed in `tree` — probing is a workaround.
- **No cache eviction.** `~/.cache/sdss_access` (or `$XDG_CACHE_HOME/sdss_access`) grows
  without bound -- nothing limits size or age, and nothing verifies an existing
  file still matches the server. A working session over many products will fill
  a disk. `fetch` treats "the target path exists" as "the cache is valid", which
  is also wrong if a download was interrupted. Needs a size/age policy and
  either checksums (as `pooch` does) or a length/ETag check.
- No CLI (#94), no progress bars (#104), no mirror failover (#102), no docs
  beyond this README, no CI.
