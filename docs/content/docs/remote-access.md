---
title: Remote access
weight: 6
---

# Remote access

`Access` wraps [`fsspec`](https://filesystem-spec.readthedocs.io/), so one backend
covers every transport SDSS cares about:

| protocol | target |
|---|---|
| `https` *(default)* | the SAS |
| `s3` | a cloud bucket — **[untested]({{< relref "/docs/limitations" >}})** |
| `file` | a local SAS mount, no download at all |

```python
from sloppy_sdss_access import SDSS, Access

a = Access(SDSS("dr19"))
repr(a)
```

```
"Access(release='dr19', protocol='https', cache=on)"
```

## Locating

```python
a.uri("astraAllStarASPCAP")
a.exists("astraAllStarASPCAP")
a.size("astraAllStarASPCAP")
```

```
'https://data.sdss.org/sas/dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'
True
1171102556
```

`uri()` is transport-aware:

```python
Access(SDSS("dr19"), protocol="s3", bucket="sdss-data").uri("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
Access(SDSS("dr19"), protocol="file").uri("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

```
's3://sdss-data/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
'/Users/acasey/sas/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits'
```

```python
Access(SDSS("dr19"), protocol="s3").uri("specLite", fieldid=1, mjd=1, catalogid=1)
```

```
ValueError: protocol='s3' requires a bucket
```

## Streaming vs fetching

This is the central distinction. Pick deliberately.

| | `open()` | `fetch()` |
|---|---|---|
| transfers | only the bytes you read | the whole file |
| returns | a file object | a `pathlib.Path` |
| cached | no (unless `block_cache=True`) | yes, whole-file |
| good for | headers, single row-groups, peeking | anything you will read repeatedly |

### `open()` — read without downloading

```python
with a.open("astraAllStarASPCAP") as fp:
    head = fp.read(64)
print(head[:4].hex(), head[:2] == b"\x1f\x8b")
```

```
1f8b0808 True
```

That read valid gzip magic out of a **1.17 GB** file. `fsspec` issues an HTTP range
request and fetches one block to serve it — not the whole file. This is
[#96](https://github.com/sdss/sdss_access/issues/96).

The obvious use is FITS headers:

```python
from astropy.io import fits
with a.open("astraAllStarASPCAP") as fp:
    header = fits.open(fp)[0].header
```

> [!INFO]
> **`open()` deliberately bypasses the whole-file cache.** `filecache` would download
> the entire file up front, which is exactly what streaming is meant to avoid.
>
> Pass `block_cache=True` to cache the byte *ranges* actually read — worth it for
> repeated random access to one large file, pointless for a single header read.

### `fetch()` — download one file

```python
a.fetch("specLite", fieldid=15000, mjd=59146, catalogid=4375924756)
```

Returns a `pathlib.Path` in the cache. The cache mirrors the SAS layout so files
stay identifiable:

```
/tmp/doccache/dr19/spectro/boss/redux/v6_1_3/spectra/lite/015000/59146/spec-015000-59146-4375924756.fits
```

## Concurrent downloads

`fetch_many()` takes a sequence of `(species, keys)` pairs and returns a list of
paths **positionally aligned** with the input.

```python
import time
items = [("specLite", dict(fieldid=15000, mjd=59146, catalogid=4375924756))]

t = time.time(); r = a.fetch_many(items); print("%.1fs" % (time.time() - t))
t = time.time(); r = a.fetch_many(items); print("%.4fs" % (time.time() - t))
print(r[0].stat().st_size)
```

```
1.4s
0.0004s
380160
```

The second call is served from cache.

This is genuinely async — `fsspec` with `asynchronous=True` plus `asyncio.gather`
under a semaphore, not a thread pool wearing an async costume. This is
[#99](https://github.com/sdss/sdss_access/issues/99).

```python
a.fetch_many(items, concurrency=8)              # default
a.fetch_many(items, skip_missing=True)          # missing -> None in its slot
```

`skip_missing=True` is [#89](https://github.com/sdss/sdss_access/issues/89): a file
that cannot be fetched yields `None` rather than aborting the batch.

### Inside an event loop

```python
await a.afetch_many(items)
```

> [!WARNING]
> `fetch_many()` **raises** if called from inside a running event loop:
>
> ```
> RuntimeError: fetch_many() cannot run inside an active event loop (e.g. Jupyter).
> Use `await access.afetch_many(...)` instead.
> ```
>
> In a notebook, use `afetch_many`.

## Caching

Fetches are cached on disk under `~/.cache/sdss_access`, or
`$XDG_CACHE_HOME/sdss_access` if that is set.

```python
Access(SDSS("dr19")).cache
```

```
PosixPath('~/.cache/sdss_access')
```

Pass `cache=None` to disable it, or `cache="/some/dir"` to relocate it.

> [!DANGER]
> ### The cache has no eviction, and no validation
>
> Be honest with yourself about this before pointing it at a large working set.
>
> * **No eviction policy.** Nothing limits the cache by size or by age. It grows
>   without bound. A working session over many products **will fill a disk**.
> * **No validation.** `fetch()` treats "the target path exists" as "the cache is
>   valid". That is wrong if a download was interrupted — you will get a truncated
>   file back, silently, forever.
> * **No freshness check.** Nothing verifies that a cached file still matches the
>   server.
>
> What it needs is a size/age policy plus either checksums (as
> [`pooch`](https://www.fatiando.org/pooch/) does) or a length/ETag check. Neither
> exists. Until then, clear it by hand:
>
> ```bash
> rm -rf ~/.cache/sdss_access
> ```

## Compression probing

Tree templates and the SAS disagree about compression more often than you would
hope. `sdsswork`'s `astraAllStarASPCAP` is templated `.fits` but stored `.fits.gz`;
DR19's template has it right:

```python
SDSS("sdsswork").path("astraAllStarASPCAP", v_astra="0.6.0")
SDSS("dr19").path("astraAllStarASPCAP")
```

```
'sdsswork/mwm/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits'
'dr19/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'
```

`Access` returns the variant that **actually exists on the server**. This is
[#66](https://github.com/sdss/sdss_access/issues/66).

```python
a = Access(SDSS("sdsswork"))
a.uri("astraAllStarASPCAP", v_astra="0.6.0")           # as templated
a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0")   # as stored
```

```
'https://data.sdss5.org/sas/sdsswork/mwm/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits'
'https://data.sdss5.org/sas/sdsswork/mwm/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'
```

`exists()`, `size()`, `open()`, `fetch()` and `fetch_many()` all go through
`resolve_uri()`. Only `uri()` and `glob()` return the raw template.

### Probing is declared, not blind

Every product carries `compression` (the suffix its template already names) and
`may_be_compressed`. Measured across the 8 SDSS-5 releases:

| case | products | probes |
|---|---|---|
| template already names `.gz`/`.bz2`/`.fz` | **142** | none |
| extension never compressed (`.png`, `.parquet`, `.h5`, `.apz`, …) | **452** | none |
| `may_be_compressed` | **1,364** | one, then cached |

### And learned once per species

The SAS does not compress one `mwmStar` and not the next, so the suffix discovered
for the first is reused for the rest:

```python
a = Access(SDSS("sdsswork"))
for i in (103020004, 103020005, 103020006):
    a.resolve_uri("mwmStar", v_astra="0.6.0", sdss_id=i)
print(a._suffix_fix)
```

```
{'mwmStar': ''}
```

One `exists()` call learned that `mwmStar` is *not* compressed; the next two cost
nothing. Similarly:

```python
a.resolve_uri("astraAllStarASPCAP", v_astra="0.6.0")
print(a._suffix_fix)
```

```
{'astraAllStarASPCAP': '.gz'}
```

| scenario | requests |
|---|---|
| `mwmStar`, 5 files | 1 `exists()`, then 0 |
| `sdsswork` `astraAllStarASPCAP` | 2, then 0 |
| `dr19` `astraAllStarASPCAP` (`.gz` already templated) | 0 |
| `probe_compression=False` | 0 |

So a loop over 10,000 stars costs **one** extra request, not 10,000.

> [!INFO]
> `sdss_access` does this by `stat`-ing the *local* filesystem, so it only
> self-corrects on a machine with a SAS mount. Remotely it returns the broken `.fits`
> URL. This works remotely.
>
> The underlying wrong templates should still be fixed in `tree` — probing is a
> workaround, not a solution.

Turn it off with `Access(..., probe_compression=False)`. Probing is also skipped
entirely for `protocol="file"`.

## Cloud (S3)

```python
Access(SDSS("dr19"), protocol="s3", bucket="some-bucket")
```

Requires the `[s3]` extra. This is
[#101](https://github.com/sdss/sdss_access/issues/101).

> [!DANGER]
> **Untested.** SDSS data is not on MAST yet, no bucket exists to check against, and
> S3 credentials are not wired — `Access.credentials` folds auth into
> `storage_options` only for `http`/`https`. URI construction is verified; nothing
> else is.

## Glob

```python
a.glob("specLite", fieldid="*", mjd=59146, catalogid=4375924756)
```

Expands wildcards in keys via the filesystem. Note this uses `uri()`, **not**
`resolve_uri()`, so no compression probing is applied.

## What is not here

* **No progress bars** — [#104](https://github.com/sdss/sdss_access/issues/104)
* **No mirror failover** — [#102](https://github.com/sdss/sdss_access/issues/102).
  `SDSS(mirror=True)` picks `https://dev-mirror.sdss.org/sas` statically; nothing
  falls back.
* **No CLI** — [#94](https://github.com/sdss/sdss_access/issues/94)
* **No resume** on an interrupted transfer
